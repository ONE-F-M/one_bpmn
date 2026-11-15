# Copyright (c) 2026, one-fm and contributors
"""Timer catch-event sweep (_refresh_timer_tasks): must restore the LIVE
workflow_state — not the compiled serialized_spec snapshot — resume past
elapsed timers with prior progress intact, and never touch serialized_spec."""

from __future__ import annotations

import json
import time

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from one_bpmn.tasks import _refresh_timer_tasks

TIMER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    id="Defs_TimerSweep" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_TimerSweep" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="mark_progress" />
    <bpmn:scriptTask id="mark_progress" name="Mark progress">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
      <bpmn:script>progress_marker = 41</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="mark_progress" targetRef="wait_a_second" />
    <bpmn:intermediateCatchEvent id="wait_a_second" name="Wait">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
      <bpmn:timerEventDefinition id="Timer_1">
        <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT1S"</bpmn:timeDuration>
      </bpmn:timerEventDefinition>
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="wait_a_second" targetRef="after_timer" />
    <bpmn:scriptTask id="after_timer" name="After timer">
      <bpmn:incoming>Flow_3</bpmn:incoming>
      <bpmn:outgoing>Flow_4</bpmn:outgoing>
      <bpmn:script>progress_marker = progress_marker + 1</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:sequenceFlow id="Flow_4" sourceRef="after_timer" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_4</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestTimerSweep(FrappeTestCase):
	def _start_instance(self):
		process = frappe.get_doc({
			"doctype": "Process",
			"process_name": f"timer-test-{frappe.generate_hash(length=6)}",
			"description": "Timer sweep test",
			"process_owner": "Administrator",
		})
		process.insert(ignore_permissions=True)

		suffix = frappe.generate_hash(length=6)
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"timer-test-model-{suffix}",
			"process_id": f"timer-test-{suffix}",
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": TIMER_XML,
		})
		model.flags.skip_editability_check = True
		model.insert(ignore_permissions=True)
		compile_process_model(model.name)

		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": model.name,
		})
		instance.insert(ignore_permissions=True)
		instance.start(initial_data={})
		return instance

	def test_sweep_resumes_past_timer_with_progress_intact(self):
		instance = self._start_instance()
		spec_snapshot_before = instance.serialized_spec

		# Mid-flight: the pre-timer script ran, the timer is WAITING
		state = json.loads(instance.workflow_state)
		self.assertEqual(instance.status, "Active")
		self.assertTrue(
			any(t.get("task_spec") == "wait_a_second" and t.get("state") == 8
				for t in state["tasks"].values()),
			"expected the timer task to be WAITING mid-flight",
		)

		time.sleep(1.2)
		_refresh_timer_tasks(instance.name)

		instance.reload()
		state = json.loads(instance.workflow_state)

		# Timer fired, downstream script ran, progress from BEFORE the sweep
		# survived (progress_marker was 41 pre-timer, 42 after) — proving the
		# sweep resumed the live state instead of re-running from scratch.
		self.assertEqual(instance.status, "Completed")
		self.assertEqual((state.get("data") or {}).get("progress_marker"), 42)

		# The compiled spec snapshot must be untouched
		self.assertEqual(instance.serialized_spec, spec_snapshot_before)

	def test_missing_workflow_state_is_safe(self):
		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": self._start_instance().process_model,
		})
		instance.insert(ignore_permissions=True)
		_refresh_timer_tasks(instance.name)  # must not raise
