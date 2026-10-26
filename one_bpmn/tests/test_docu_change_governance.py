# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Docu doctype changes are routed by process ownership.

AC1  not an owner of a process listing the doctype -> logged as a Doctype Change
     Request, applied only when a Process Owner of a listing process approves.
AC2  owner of a process listing the doctype        -> applied at once, no request.
AC3  doctype listed under no process               -> Docu asks whether to list it
     in the current process, and does so when told to.

Every process, owner and doctype here is created by the test; nothing relies on
seeded data or fixed names.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import (
	apply_doctype,
	approve_doctype_change,
	reject_doctype_change,
)

REQUEST = "Doctype Change Request"


class TestDocuChangeGovernance(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		tag = frappe.generate_hash(length=6)
		self.doctype = "Zz Gov Probe " + tag.upper()
		self.users = {key: f"zz_gov_{key}_{tag}@example.com" for key in ("a", "b", "c")}
		for key, email in self.users.items():
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": f"Gov {key}",
				"send_welcome_email": 0, "enabled": 1,
				"roles": [{"role": "System Manager"}],
			}).insert(ignore_permissions=True)
		self.processes = []
		self.tag = tag
		# the doctype under governance, created (ungoverned: nothing lists it yet)
		apply_doctype(self._ir(), confirm=1)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(REQUEST, filters={"target_doctype": self.doctype}, pluck="name"):
			frappe.delete_doc(REQUEST, name, force=True, ignore_permissions=True)
		for name in self.processes:
			if frappe.db.exists("Process", name):
				frappe.delete_doc("Process", name, force=True, ignore_permissions=True)
		if frappe.db.exists("DocType", self.doctype):
			frappe.delete_doc("DocType", self.doctype, force=True, ignore_permissions=True)
		for email in self.users.values():
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()

	# ── helpers ────────────────────────────────────────────────────────────
	def _ir(self, extra=False):
		fields = [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}]
		if extra:
			fields.append({"fieldname": "extra", "fieldtype": "Data", "label": "Extra"})
		return json.dumps({"doctype_name": self.doctype, "module": "ONE BPMN", "fields": fields})

	def _process(self, key, owner, lists_doctype=True):
		name = f"Zz Gov Process {key} {self.tag}"
		frappe.get_doc({
			"doctype": "Process", "process_name": name, "description": "governance test",
			"process_owner": self.users[owner],
			"process_doctypes": [{"document_type": self.doctype}] if lists_doctype else [],
		}).insert(ignore_permissions=True)
		self.processes.append(name)
		return name

	def _has_extra(self):
		return bool(frappe.db.exists("DocField", {"parent": self.doctype, "fieldname": "extra"}))

	def _requests(self):
		return frappe.get_all(REQUEST, filters={"target_doctype": self.doctype}, fields=["name", "status", "requested_by"])

	def _listed_in(self, process):
		return bool(frappe.db.exists(
			"Process Doctype", {"parent": process, "parenttype": "Process", "document_type": self.doctype}))

	# ── AC1 ────────────────────────────────────────────────────────────────
	def test_non_owner_change_is_logged_not_applied(self):
		self._process("one", "a")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(extra=True), confirm=1)

		self.assertEqual(out["status"], "pending_approval")
		self.assertFalse(self._has_extra(), "the change must not be applied before approval")
		reqs = self._requests()
		self.assertEqual(len(reqs), 1)
		self.assertEqual(reqs[0].status, "Pending")
		self.assertEqual(reqs[0].requested_by, self.users["b"])
		self.assertEqual(out["request"], reqs[0].name)

	def test_repeated_edits_keep_one_pending_request(self):
		self._process("one", "a")
		frappe.set_user(self.users["b"])
		first = apply_doctype(self._ir(), confirm=1)
		second = apply_doctype(self._ir(extra=True), confirm=1)

		self.assertEqual(first["request"], second["request"])
		reqs = self._requests()
		self.assertEqual(len(reqs), 1)
		stored = json.loads(frappe.db.get_value(REQUEST, reqs[0].name, "requested_ir"))
		self.assertIn("extra", [f["fieldname"] for f in stored["fields"]])

	def test_any_owner_of_a_listing_process_can_approve(self):
		self._process("one", "a")
		self._process("two", "c")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(extra=True), confirm=1)
		self.assertEqual(sorted(out["processes"]), sorted(self.processes))

		# the requester is not an owner, so cannot approve their own request
		with self.assertRaises(frappe.PermissionError):
			approve_doctype_change(out["request"], confirm=1)
		self.assertFalse(self._has_extra())

		frappe.set_user(self.users["c"])
		result = approve_doctype_change(out["request"], confirm=1)
		self.assertEqual(result["status"], "applied")
		self.assertTrue(self._has_extra())
		self.assertEqual(frappe.db.get_value(REQUEST, out["request"], "status"), "Approved")
		self.assertEqual(frappe.db.get_value(REQUEST, out["request"], "reviewed_by"), self.users["c"])

	def test_rejecting_a_request_applies_nothing(self):
		self._process("one", "a")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(extra=True), confirm=1)

		frappe.set_user(self.users["a"])
		reject_doctype_change(out["request"], reason="not aligned")
		self.assertEqual(frappe.db.get_value(REQUEST, out["request"], "status"), "Rejected")
		self.assertFalse(self._has_extra())
		with self.assertRaises(frappe.ValidationError):
			approve_doctype_change(out["request"], confirm=1)

	# ── AC2 ────────────────────────────────────────────────────────────────
	def test_owner_change_is_applied_immediately_without_a_request(self):
		self._process("one", "a")
		self._process("two", "c")
		frappe.set_user(self.users["a"])
		out = apply_doctype(self._ir(extra=True), confirm=1)

		self.assertEqual(out["status"], "applied")
		self.assertTrue(self._has_extra())
		self.assertEqual(self._requests(), [])

	# ── AC3 ────────────────────────────────────────────────────────────────
	def test_unlisted_doctype_asks_before_applying(self):
		process = self._process("one", "a", lists_doctype=False)
		frappe.set_user(self.users["a"])
		out = apply_doctype(self._ir(extra=True), confirm=1, process=process)

		self.assertEqual(out["status"], "needs_listing_decision")
		self.assertEqual(out["process"], process)
		self.assertFalse(self._has_extra(), "nothing is applied until the question is answered")
		self.assertFalse(self._listed_in(process))
		self.assertEqual(self._requests(), [])

	def test_accepting_lists_the_doctype_and_applies(self):
		process = self._process("one", "a", lists_doctype=False)
		frappe.set_user(self.users["a"])
		out = apply_doctype(self._ir(extra=True), confirm=1, process=process, list_in_process=1)

		self.assertEqual(out["status"], "applied")
		self.assertEqual(out["listed_in_process"], process)
		self.assertTrue(self._has_extra())
		self.assertTrue(self._listed_in(process))
		self.assertEqual(self._requests(), [])

	def test_declining_applies_without_listing(self):
		process = self._process("one", "a", lists_doctype=False)
		frappe.set_user(self.users["a"])
		out = apply_doctype(self._ir(extra=True), confirm=1, process=process, list_in_process="0")

		self.assertEqual(out["status"], "applied")
		self.assertTrue(self._has_extra())
		self.assertFalse(self._listed_in(process))

	def test_only_the_owner_can_list_a_doctype_in_a_process(self):
		process = self._process("one", "a", lists_doctype=False)
		frappe.set_user(self.users["b"])
		with self.assertRaises(frappe.PermissionError):
			apply_doctype(self._ir(extra=True), confirm=1, process=process, list_in_process=1)
		self.assertFalse(self._has_extra())
		self.assertFalse(self._listed_in(process))
