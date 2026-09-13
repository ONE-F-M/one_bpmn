# Copyright (c) 2026, one-fm and contributors
"""Timer Start Event sweep: the cycle a modeller writes into <bpmn:timeCycle>
must schedule the instance, the compiled spec must not re-evaluate that cycle
as a SpiffWorkflow timer, and one unreadable cycle must not cost every other
timer model its turn."""

from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from one_bpmn.tasks import process_timer_start_events, timer_start_is_due

TIMER_START_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    id="Defs_TimerStart" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="PROCESS_ID" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
      <bpmn:timerEventDefinition id="Timer_1">
        <bpmn:timeCycle xsi:type="bpmn:tFormalExpression">CYCLE</bpmn:timeCycle>
      </bpmn:timerEventDefinition>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="do_work" />
    <bpmn:scriptTask id="do_work" name="Do work">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
      <bpmn:script>timer_ran = True</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="do_work" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestTimerStartSweep(FrappeTestCase):
	def setUp(self):
		self.deployed = []

	def tearDown(self):
		# The sweep commits each instance it starts, so the test transaction's
		# rollback cannot take these back — an active timer map left behind here
		# would go on firing on the developer's own site every minute.
		for model_name, process_name in reversed(self.deployed):
			for instance in frappe.get_all(
				"BPMN Process Instance", filters={"process_model": model_name}, pluck="name"
			):
				frappe.delete_doc("BPMN Process Instance", instance, force=True, ignore_permissions=True)
			frappe.delete_doc("BPMN Process Model", model_name, force=True, ignore_permissions=True)
			frappe.delete_doc("Process", process_name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _deploy(self, cycle: str):
		suffix = frappe.generate_hash(length=6)
		process = frappe.get_doc({
			"doctype": "Process",
			"process_name": f"timer-start-{suffix}",
			"description": "Timer start sweep test",
			"process_owner": "Administrator",
		})
		process.insert(ignore_permissions=True)

		process_id = f"Process_TimerStart_{suffix}"
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"timer-start-model-{suffix}",
			"process_id": process_id,
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": TIMER_START_XML.replace("PROCESS_ID", process_id).replace("CYCLE", cycle),
		})
		model.flags.skip_editability_check = True
		model.insert(ignore_permissions=True)
		# Registered before the compile, which is itself under test and may throw.
		self.deployed.append((model.name, process.name))
		compile_process_model(model.name)
		model.reload()
		model.db_set("is_active", 1)
		return model

	def _instances(self, model_name: str) -> list[dict]:
		return frappe.get_all(
			"BPMN Process Instance",
			filters={"process_model": model_name},
			fields=["name", "status"],
		)

	def test_cron_cycle_starts_and_completes_an_instance(self):
		model = self._deploy("* * * * *")

		# The scheduler owns the start event's timing, so the compiled spec must
		# carry a plain start event — a cycle timer here evaluates "* * * * *"
		# as Python and errors the instance on its first step.
		spec = json.loads(model.serialized_spec)
		start = spec["spec"]["task_specs"]["StartEvent_1"]
		self.assertEqual(start["event_definition"]["typename"], "NoneEventDefinition")

		process_timer_start_events()

		instances = self._instances(model.name)
		self.assertEqual(len(instances), 1)
		self.assertEqual(instances[0]["status"], "Completed")

	def test_unreadable_cycle_does_not_cost_a_healthy_model_its_turn(self):
		healthy = self._deploy("* * * * *")
		broken = self._deploy("* * * * *")
		# Compile refuses a cycle the sweep cannot read, so plant it afterwards —
		# the rows on site predate that check.
		frappe.db.set_value(
			"BPMN Start Event Config",
			{"parent": broken.name},
			"cron_expression",
			"every day please",
			update_modified=False,
		)

		process_timer_start_events()

		self.assertEqual(len(self._instances(healthy.name)), 1)
		self.assertEqual(len(self._instances(broken.name)), 0)

	def test_patch_repairs_a_spec_that_still_carries_its_timer(self):
		model = self._deploy("* * * * *")
		spec = json.loads(model.serialized_spec)
		spec["spec"]["task_specs"]["StartEvent_1"]["event_definition"] = {
			"description": "Timer",
			"name": "Start",
			"expression": "* * * * *",
			"typename": "CycleTimerEventDefinition",
		}
		model.db_set("serialized_spec", json.dumps(spec), update_modified=False)

		from one_bpmn.one_bpmn.patches.v1_0.detach_timer_start_event_definitions import execute

		execute()

		model.reload()
		start = json.loads(model.serialized_spec)["spec"]["task_specs"]["StartEvent_1"]
		self.assertEqual(start["event_definition"]["typename"], "NoneEventDefinition")

		process_timer_start_events()
		self.assertEqual(self._instances(model.name)[0]["status"], "Completed")

	def test_compile_rejects_a_timer_start_event_it_cannot_schedule(self):
		with self.assertRaises(frappe.ValidationError):
			self._deploy("every day please")
		with self.assertRaises(frappe.ValidationError):
			self._deploy("")

	def test_iso_repeating_interval_is_due_on_its_occurrence_minute(self):
		# Asia/Kuwait is +03:00, the offset the maps on site are authored in.
		daily = "R/2026-09-07T00:00:00+03:00/P1D"
		self.assertTrue(timer_start_is_due(daily, datetime(2026, 9, 9, 0, 0, 10)))
		self.assertFalse(timer_start_is_due(daily, datetime(2026, 9, 9, 0, 1, 0)))
		self.assertFalse(timer_start_is_due(daily, datetime(2026, 9, 6, 0, 0, 0)))

		twice = "R2/2026-09-07T00:00:00+03:00/P1D"
		self.assertTrue(timer_start_is_due(twice, datetime(2026, 9, 8, 0, 0, 5)))
		self.assertFalse(timer_start_is_due(twice, datetime(2026, 9, 9, 0, 0, 5)))

	def test_cron_expression_matches_the_minute(self):
		self.assertTrue(timer_start_is_due("*/5 * * * *", datetime(2026, 9, 9, 13, 15, 0)))
		self.assertFalse(timer_start_is_due("*/5 * * * *", datetime(2026, 9, 9, 13, 16, 0)))
		self.assertFalse(timer_start_is_due("", datetime(2026, 9, 9, 13, 16, 0)))
