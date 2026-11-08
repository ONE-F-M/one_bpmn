# Copyright (c) 2026, one-fm and contributors
"""Cancel a submitted Journal Entry through its cancellation map instead of directly."""

from unittest.mock import patch

import frappe
from frappe.desk.doctype.bulk_update.bulk_update import submit_cancel_or_update_docs
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import instances
from one_bpmn.api.deploy import compile_process_model
from one_bpmn.processa_engine.instances.cancellation import set_pending_cancellation_onload
from one_bpmn.processa_engine.instances.listing import clear_processa_doctype_cache

COMPANY = "One Facilities Management"

CANCELLATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_CancelRequest" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_CancelRequest" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" spiffworkflow:triggerDoctype="Journal Entry"
        spiffworkflow:triggerType="On Cancel Request">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="review" />
    <bpmn:userTask id="review" name="Review cancellation" spiffworkflow:assigneeMode="User"
        spiffworkflow:assigneeUser="Administrator"
        spiffworkflow:taskActions="[{&quot;action&quot;:&quot;Approve&quot;},{&quot;action&quot;:&quot;Reject&quot;}]">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="review" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


def _cancellation_map():
	suffix = frappe.generate_hash(length=6)
	process = frappe.get_doc(
		{
			"doctype": "Process",
			"process_name": f"cancel-request-{suffix}",
			"description": "Cancellation request test",
			"process_owner": "Administrator",
		}
	).insert()
	model = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": f"cancel-request-model-{suffix}",
			"process_id": f"cancel-request-{suffix}",
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": CANCELLATION_XML,
		}
	)
	model.flags.skip_editability_check = True
	model.insert()
	compile_process_model(model.name)
	return model.name


def _journal_entry():
	accounts = frappe.get_all(
		"Account",
		filters={"company": COMPANY, "is_group": 0, "disabled": 0, "account_type": ["in", ["Cash", "Bank"]]},
		pluck="name",
		limit=2,
	)
	journal_entry = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": COMPANY,
			"posting_date": frappe.utils.today(),
			"accounts": [
				{"account": accounts[0], "debit_in_account_currency": 1},
				{"account": accounts[1], "credit_in_account_currency": 1},
			],
		}
	).insert()
	journal_entry.submit()
	return journal_entry


def _review(instance_name, approved):
	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	task_id = next(row.task_id for row in instance.active_tasks if row.status == "Waiting")
	instance.advance(task_id=task_id, data={"cancellation_approved": approved})
	return frappe.get_doc("BPMN Process Instance", instance_name)


def _docstatus(journal_entry):
	return frappe.db.get_value("Journal Entry", journal_entry.name, "docstatus")


class CancellationRequestTestCase(FrappeTestCase):
	def setUp(self):
		# A failed engine pass commits; keep the fixtures inside the test transaction.
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		clear_processa_doctype_cache()
		# The cached map list must not outlive the rolled-back test map.
		self.addCleanup(clear_processa_doctype_cache)
		# FrappeTestCase rolls back once per class; each test here needs its own clean slate.
		frappe.db.savepoint("cancellation_request")
		self.addCleanup(frappe.db.rollback, save_point="cancellation_request")
		self.journal_entry = _journal_entry()

	def _request(self):
		return instances.request_cancellation("Journal Entry", self.journal_entry.name)

	def test_cancel_request_starts_the_map_and_keeps_the_entry_submitted(self):
		_cancellation_map()
		result = self._request()
		self.assertEqual(result["status"], "Active")
		self.assertEqual(_docstatus(self.journal_entry), 1)

	def test_approval_cancels_the_entry(self):
		_cancellation_map()
		instance = _review(self._request()["instance"], True)
		self.assertEqual(instance.status, "Completed")
		self.assertEqual(
			(instance.context_doctype, instance.context_docname), ("Journal Entry", self.journal_entry.name)
		)
		self.assertEqual(_docstatus(self.journal_entry), 2)

	def test_rejection_keeps_the_entry_submitted(self):
		_cancellation_map()
		instance = _review(self._request()["instance"], False)
		self.assertEqual(instance.status, "Completed")
		self.assertEqual(_docstatus(self.journal_entry), 1)

	def test_second_request_is_refused_and_the_form_shows_it_pending(self):
		_cancellation_map()
		first = self._request()["instance"]
		with self.assertRaises(frappe.ValidationError):
			self._request()
		self.assertEqual(
			frappe.db.count("BPMN Process Instance", {"context_docname": self.journal_entry.name}), 1
		)
		doc = frappe.get_doc("Journal Entry", self.journal_entry.name)
		set_pending_cancellation_onload(doc, "onload")
		self.assertEqual(doc.get_onload().pending_cancellation, first)

	def test_without_a_map_cancel_works_as_before(self):
		frappe.get_doc("Journal Entry", self.journal_entry.name).cancel()
		self.assertEqual(_docstatus(self.journal_entry), 2)
		with self.assertRaises(frappe.ValidationError):
			self._request()

	def test_direct_and_bulk_cancel_are_refused_when_a_map_exists(self):
		_cancellation_map()
		with self.assertRaisesRegex(frappe.ValidationError, "press Cancel to request it"):
			frappe.client.cancel("Journal Entry", self.journal_entry.name)
		with patch.object(frappe.db, "rollback"):
			failed = submit_cancel_or_update_docs("Journal Entry", [self.journal_entry.name], action="cancel")
		self.assertEqual(failed, [self.journal_entry.name])
		self.assertEqual(_docstatus(self.journal_entry), 1)

	def test_request_needs_cancel_permission(self):
		_cancellation_map()
		with self.set_user("Guest"), self.assertRaises(frappe.PermissionError):
			self._request()
		self.assertFalse(
			frappe.db.exists("BPMN Process Instance", {"context_docname": self.journal_entry.name})
		)
