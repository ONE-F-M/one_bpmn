# Copyright (c) 2026, one-fm and contributors
"""A run that starts inside another run must leave the engine flag as it found it.

A script in a running map can insert a document that starts a second map (an
assigned Blocker inserts a ToDo, and a map starts on ToDo After Insert). The
second run used to clear frappe.flags.bpmn_engine_action on exit, so the first
run's next apply_workflow submit was refused by guard_bpmn_document as a direct
submit of a document under an active process.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Defs_FlagRestore" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_FlagRestore" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_In</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_In" sourceRef="StartEvent_1" targetRef="Task_Wait" />
    <bpmn:userTask id="Task_Wait" name="Wait"><bpmn:incoming>Flow_In</bpmn:incoming><bpmn:outgoing>Flow_Out</bpmn:outgoing></bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_Out" sourceRef="Task_Wait" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_Out</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestEngineFlagRestoredAfterNestedRun(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(setattr, frappe.flags, "bpmn_engine_action", frappe.flags.bpmn_engine_action)

	def _instance(self):
		from one_bpmn.api.compilation import compile_process_model

		suffix = frappe.generate_hash(length=6)
		process = frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": f"flag-restore-{suffix}",
				"description": "engine flag test",
				"process_owner": "Administrator",
			}
		).insert()
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"flag-restore-model-{suffix}",
				"process_id": f"flag-restore-{suffix}",
				"version": 1,
				"process_name": process.name,
				"bpmn_xml": MODEL_XML,
			}
		)
		model.flags.skip_editability_check = True
		model.insert()
		compile_process_model(model.name)
		return frappe.get_doc({"doctype": "BPMN Process Instance", "process_model": model.name}).insert()

	def test_nested_start_leaves_the_outer_flag_set(self):
		frappe.flags.bpmn_engine_action = True

		self._instance().start(initial_data={})

		self.assertTrue(frappe.flags.bpmn_engine_action)

	def test_top_level_start_leaves_the_flag_clear(self):
		frappe.flags.bpmn_engine_action = False

		self._instance().start(initial_data={})

		self.assertFalse(frappe.flags.bpmn_engine_action)
