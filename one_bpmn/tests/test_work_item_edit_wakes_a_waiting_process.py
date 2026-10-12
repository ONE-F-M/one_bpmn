# Copyright (c) 2026, one-fm and contributors
"""A process waiting for the Work Item to be assigned to the orchestrator again is woken by an edit and reads the live flag."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model

MODEL = "WI Retry Wait"
PROCESS_ID = "wi_retry_wait_process"
MAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_{PROCESS_ID}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:message id="Msg_edit" name="WorkItem_Edit_Action" />
  <bpmn:process id="{PROCESS_ID}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="wait" />
    <bpmn:intermediateCatchEvent id="wait" name="Wait">
      <bpmn:incoming>f1</bpmn:incoming><bpmn:incoming>f_no</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_edit" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="f2" sourceRef="wait" targetRef="gw" />
    <bpmn:exclusiveGateway id="gw" name="Assigned again?">
      <bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f_yes</bpmn:outgoing><bpmn:outgoing>f_no</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:sequenceFlow id="f_yes" sourceRef="gw" targetRef="mark"><bpmn:conditionExpression>doc.orchestrator</bpmn:conditionExpression></bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="f_no" sourceRef="gw" targetRef="wait"><bpmn:conditionExpression>not doc.orchestrator</bpmn:conditionExpression></bpmn:sequenceFlow>
    <bpmn:scriptTask id="mark" name="Restart"><bpmn:incoming>f_yes</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing><bpmn:script>restarted = True</bpmn:script></bpmn:scriptTask>
    <bpmn:sequenceFlow id="f3" sourceRef="mark" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


class TestAnEditWakesTheWait(FrappeTestCase):
	def setUp(self):
		source = frappe.db.get_value("Work Item", {}, "name")
		if not source:
			self.skipTest("the site has no Work Item to copy")
		item = frappe.copy_doc(frappe.get_doc("Work Item", source))
		item.title = f"_Test retry wait {frappe.generate_hash(length=8)}"
		item.orchestrator = 0
		item.assignee_user = None
		item.pr_link = None
		item.insert(ignore_permissions=True)
		self.work_item = item.name
		# A Work Item insert starts the maps configured for it; this test is about its own process only.
		for started in frappe.get_all("BPMN Process Instance", filters={"context_docname": item.name}, pluck="name"):
			frappe.delete_doc("BPMN Process Instance", started, force=True, ignore_permissions=True)
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1, ignore_permissions=True)
		model = frappe.new_doc("BPMN Process Model")
		model.name, model.title, model.process_id, model.bpmn_xml, model.version = MODEL, MODEL, PROCESS_ID, MAP, 1
		model.insert(ignore_permissions=True)
		compile_process_model(model.name)
		self.instance = frappe.new_doc("BPMN Process Instance")
		self.instance.process_model = MODEL
		self.instance.context_doctype = "Work Item"
		self.instance.context_docname = self.work_item
		self.instance.insert(ignore_permissions=True)
		self.instance.start()
		self.addCleanup(self._clean)

	def _clean(self):
		for doctype, name in (("BPMN Process Instance", self.instance.name), ("BPMN Process Model", MODEL)):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		frappe.db.rollback()

	def _status(self):
		self.instance.reload()
		return self.instance.status

	def _edit(self, **fields):
		# The platform delivers one edit message per document per request; each edit here is its own request.
		frappe.flags._bpmn_message_sent = set()
		frappe.flags._bpmn_instances_just_started = set()
		item = frappe.get_doc("Work Item", self.work_item)
		item.update(fields)
		item.save(ignore_permissions=True)

	def test_it_is_waiting_after_the_start(self):
		self.assertEqual(self._status(), "Active")

	def test_an_edit_with_the_flag_still_off_keeps_it_waiting(self):
		self._edit(priority=frappe.db.get_value("Work Item", self.work_item, "priority"))
		self.assertEqual(self._status(), "Active")

	def test_ticking_the_orchestrator_flag_restarts_it(self):
		self._edit(orchestrator=1)
		self.assertEqual(self._status(), "Completed")
		data = json.loads(self.instance.workflow_state or "{}").get("data") or {}
		self.assertTrue(data.get("restarted"))

	def test_it_reads_the_flag_as_it_is_now_not_as_it_was(self):
		self._edit(orchestrator=1)
		self.assertEqual(self._status(), "Completed")
