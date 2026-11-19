# Copyright (c) 2026, one-fm and contributors
"""Document events and the instances they touch.

A document event raised by the engine itself must not advance the instance again, and a
document saved while its instance starts comes back with what the first engine pass wrote.
"""

import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.deploy import compile_process_model
from processa.processa_engine import triggers


class TestTriggerEngineReentry(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.doc = frappe.get_doc({"doctype": "ToDo", "description": "reentry probe"})
		self.doc.name = "TODO-REENTRY"
		self.previous_flag = frappe.flags.bpmn_engine_action
		self.addCleanup(setattr, frappe.flags, "bpmn_engine_action", self.previous_flag)

	@mock.patch.object(triggers, "_advance_instance_on_doc_event")
	@mock.patch.object(triggers.frappe, "get_all", return_value=["INST-1"])
	def test_engine_raised_event_does_not_advance(self, _get_all, advance):
		frappe.flags.bpmn_engine_action = True

		triggers._maybe_advance_instances(self.doc, "Submit")

		advance.assert_not_called()

	@mock.patch.object(triggers, "_advance_instance_on_doc_event")
	@mock.patch.object(triggers.frappe, "get_all", return_value=["INST-1"])
	def test_user_raised_event_still_advances(self, _get_all, advance):
		frappe.flags.bpmn_engine_action = False

		triggers._maybe_advance_instances(self.doc, "Submit")

		advance.assert_called_once_with("INST-1", "Submit")


RESET_ROWS = json.dumps([{"field": "status", "value": "Open"}]).replace('"', "&quot;")
RESET_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs_refresh_on_start">
  <bpmn:process id="refresh_on_start" isExecutable="true">
    <bpmn:startEvent id="created" spiffworkflow:triggerDoctype="ToDo" spiffworkflow:triggerType="After Insert" />
    <bpmn:serviceTask id="reset" name="Set to Open" spiffworkflow:serviceType="update_field"
        spiffworkflow:updateFieldDoctype="ToDo" spiffworkflow:updateFieldRows="{RESET_ROWS}" />
    <bpmn:endEvent id="done" />
    <bpmn:sequenceFlow id="f1" sourceRef="created" targetRef="reset" />
    <bpmn:sequenceFlow id="f2" sourceRef="reset" targetRef="done" />
  </bpmn:process>
</bpmn:definitions>"""


class TestRefreshContextDocOnStart(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.closed_todo = frappe.get_doc(
			doctype="ToDo", description="refresh on start", allocated_to="Administrator", status="Closed"
		).insert()
		model = frappe.get_doc(
			doctype="BPMN Process Model",
			title=f"refresh-on-start-{frappe.generate_hash(length=6)}",
			process_id="refresh_on_start",
			version=1,
			bpmn_xml=RESET_XML,
		)
		model.flags.skip_editability_check = True
		model.insert()
		compile_process_model(model.name)
		cls.model = model.name

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_value("BPMN Process Model", cls.model, "is_active", 0)
		super().tearDownClass()

	def test_duplicated_document_shows_the_state_the_map_set(self):
		duplicate = frappe.copy_doc(self.closed_todo)
		self.assertEqual(duplicate.status, "Closed")

		duplicate.insert()

		self.assertTrue(
			frappe.db.exists(
				"BPMN Process Instance", {"process_model": self.model, "context_docname": duplicate.name}
			)
		)
		self.assertEqual(duplicate.status, "Open")
		self.assertEqual(
			str(duplicate.modified), str(frappe.db.get_value("ToDo", duplicate.name, "modified"))
		)

	def test_the_refreshed_document_saves_again_without_a_conflict(self):
		duplicate = frappe.copy_doc(self.closed_todo).insert()

		duplicate.description = "edited after the map ran"
		duplicate.save()

		self.assertEqual(frappe.db.get_value("ToDo", duplicate.name, "status"), "Open")
