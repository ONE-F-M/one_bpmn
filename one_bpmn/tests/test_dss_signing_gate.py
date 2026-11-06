# Copyright (c) 2026, one-fm and contributors
"""A task action flagged Sign cannot complete without a DSS signature, and the signing endpoints guard their callers.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_dss_signing_gate
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import instance_api
from one_bpmn.api.compilation import compile_process_model

SIGN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_DssGate" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_DssGate" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="sign_off" />
    <bpmn:userTask id="sign_off" name="Sign Off"
        spiffworkflow:assigneeMode="User"
        spiffworkflow:assigneeUser="Administrator"
        spiffworkflow:taskActions="[{&quot;action&quot;:&quot;Sign Off&quot;,&quot;requireDigitalSignature&quot;:&quot;true&quot;},{&quot;action&quot;:&quot;Reject&quot;}]">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="sign_off" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


def _signature_log(todo, user="Administrator", action="Sign Off", status="Success"):
	return frappe.get_doc(
		{
			"doctype": "DSS Response Log",
			"signature_id": f"test-{frappe.generate_hash(length=6)}",
			"status": status,
			"reference_doctype": "ToDo",
			"reference_docname": todo.name,
			"requester": user,
			"workflow_action": action,
		}
	).insert()


class TestDssSigningGate(FrappeTestCase):
	def setUp(self):
		# _record_runtime_failure commits; keep the fixtures inside the test transaction.
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)

		self.signer = patch.object(instance_api, "signer_outcome", return_value="ok")
		self.signer.start()
		self.addCleanup(self.signer.stop)

		suffix = frappe.generate_hash(length=6)
		process = frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": f"dss-gate-{suffix}",
				"description": "DSS gate test",
				"process_owner": "Administrator",
			}
		).insert()
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"dss-gate-model-{suffix}",
				"process_id": f"dss-gate-{suffix}",
				"version": 1,
				"process_name": process.name,
				"bpmn_xml": SIGN_XML,
			}
		)
		model.flags.skip_editability_check = True
		model.insert()
		compile_process_model(model.name)

		self.todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "DSS gate test", "allocated_to": "Administrator"}
		).insert()
		self.instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": model.name,
				"context_doctype": "ToDo",
				"context_docname": self.todo.name,
			}
		).insert()
		self.instance.start()
		self.instance.reload()
		self.task_id = self.instance.active_tasks[0].task_id

	def _complete(self, action):
		return instance_api.complete_task(
			self.instance.name, self.task_id, json.dumps({"action": action})
		)

	def test_flagged_action_is_refused_without_a_signature(self):
		with self.assertRaises(frappe.PermissionError):
			self._complete("Sign Off")

	def test_flagged_action_completes_after_a_signature(self):
		_signature_log(self.todo)
		self.assertEqual(self._complete("Sign Off")["status"], "Completed")

	def test_signature_by_someone_else_does_not_count(self):
		_signature_log(self.todo, user="Guest")
		with self.assertRaises(frappe.PermissionError):
			self._complete("Sign Off")

	def test_signature_for_another_action_does_not_count(self):
		_signature_log(self.todo, action="Approve")
		with self.assertRaises(frappe.PermissionError):
			self._complete("Sign Off")

	def test_failed_signature_does_not_count(self):
		_signature_log(self.todo, status="Failed")
		with self.assertRaises(frappe.PermissionError):
			self._complete("Sign Off")

	def test_exempt_signer_completes_a_flagged_action_without_a_signature(self):
		with patch.object(instance_api, "signer_outcome", return_value="skip"):
			self.assertEqual(self._complete("Sign Off")["status"], "Completed")

	def test_unflagged_action_needs_no_signature(self):
		self.assertEqual(self._complete("Reject")["status"], "Completed")

	def test_start_signing_refuses_an_unflagged_action(self):
		with self.assertRaises(frappe.ValidationError):
			instance_api.start_dss_signing(self.instance.name, self.task_id, "Reject")

	def test_start_signing_runs_the_signing_process_on_the_document(self):
		with patch.object(instance_api, "start_process", return_value={"instance": "SIGN-1"}) as start:
			out = instance_api.start_dss_signing(self.instance.name, self.task_id, "Sign Off")

		self.assertEqual(out["instance"], "SIGN-1")
		start.assert_called_once_with(
			model_name=instance_api.DSS_SIGNING_MODEL,
			context_doctype="ToDo",
			context_docname=self.todo.name,
			initial_data=json.dumps({"workflow_action": "Sign Off"}),
		)

	def test_status_refuses_a_run_that_is_not_a_signing_run(self):
		with self.assertRaises(frappe.PermissionError):
			instance_api.get_dss_signing_status(self.instance.name, "Sign Off")
