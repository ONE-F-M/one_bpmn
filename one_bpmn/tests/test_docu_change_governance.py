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
	can_change_forms,
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

	# ── approvers ──────────────────────────────────────────────────────────
	def test_the_request_lists_every_owner_as_an_approver(self):
		self._process("one", "a")
		self._process("two", "c")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(extra=True), confirm=1)

		rows = frappe.get_doc(REQUEST, out["request"]).approvers
		self.assertEqual(
			sorted((r.process_name, r.approver, r.source) for r in rows),
			sorted((p, self.users[k], "Listed") for p, k in zip(self.processes, ("a", "c"))),
		)
		self.assertIn(self.processes[0], out["message"])

	def test_the_approvers_follow_a_change_of_owner(self):
		process = self._process("one", "a")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(), confirm=1)

		frappe.set_user("Administrator")
		frappe.db.set_value("Process", process, "process_owner", self.users["c"])
		frappe.set_user(self.users["b"])
		apply_doctype(self._ir(extra=True), confirm=1)

		rows = frappe.get_doc(REQUEST, out["request"]).approvers
		self.assertEqual([(r.process_name, r.approver) for r in rows], [(process, self.users["c"])])

	def test_an_unlisted_existing_doctype_goes_to_the_fallback_approvers(self):
		requester = self._plain_user("j")
		process = self._process("one", "j", lists_doctype=False)
		frappe.set_user(requester)
		out = apply_doctype(self._ir(extra=True), confirm=1, process=process, list_in_process="0")

		self.assertEqual(out["status"], "pending_approval")
		self.assertFalse(self._has_extra())
		rows = frappe.get_doc(REQUEST, out["request"]).approvers
		self.assertEqual([(r.approver_role, r.source) for r in rows], [("System Manager", "Fallback")])

		frappe.set_user(self.users["a"])
		self.assertEqual(approve_doctype_change(out["request"], confirm=1)["status"], "applied")
		self.assertTrue(self._has_extra())

	def test_an_unlisted_doctype_without_a_process_also_goes_to_the_fallback(self):
		requester = self._plain_user("k")
		frappe.set_user(requester)
		out = apply_doctype(self._ir(extra=True), confirm=1)

		self.assertEqual(out["status"], "pending_approval")
		self.assertFalse(self._has_extra())

	def test_a_new_doctype_is_created_without_an_approval(self):
		creator = self._plain_user("l")
		self._process("one", "l", lists_doctype=False)
		new_name = self.doctype + " New"
		self.addCleanup(self._drop_doctype, new_name)
		frappe.set_user(creator)
		ir = json.dumps({
			"doctype_name": new_name, "module": "ONE BPMN",
			"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
		})

		self.assertEqual(apply_doctype(ir, confirm=1)["status"], "applied")

	def _drop_doctype(self, name):
		frappe.set_user("Administrator")
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)

	def test_the_patch_fills_the_approvers_of_a_pending_request(self):
		self._process("one", "a")
		request = frappe.get_doc({
			"doctype": REQUEST, "target_doctype": self.doctype, "requested_by": self.users["b"],
			"status": "Pending", "requested_ir": self._ir(extra=True),
		}).insert(ignore_permissions=True)
		self.assertEqual(request.approvers, [])

		from one_bpmn.one_bpmn.patches.v1_0.fill_doctype_change_approvers import execute

		execute()

		rows = frappe.get_doc(REQUEST, request.name).approvers
		self.assertEqual([(r.approver, r.source) for r in rows], [(self.users["a"], "Listed")])

	# ── who can see a request ──────────────────────────────────────────────
	def _plain_user(self, key):
		email = f"zz_gov_{key}_{self.tag}@example.com"
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": f"Gov {key}",
			"send_welcome_email": 0, "enabled": 1,
			"roles": [{"role": "Employee"}],
		}).insert(ignore_permissions=True)
		self.users[key] = email
		return email

	def test_a_process_owner_without_a_role_can_see_the_request(self):
		owner = self._plain_user("d")
		self._process("one", "d")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(extra=True), confirm=1)

		frappe.set_user(owner)
		self.assertTrue(frappe.has_permission(REQUEST, "read", doc=out["request"]))
		self.assertEqual([r.name for r in frappe.get_list(REQUEST, fields=["name"])], [out["request"]])

	def test_an_unrelated_user_cannot_see_the_request(self):
		stranger = self._plain_user("e")
		self._process("one", "a")
		frappe.set_user(self.users["b"])
		out = apply_doctype(self._ir(extra=True), confirm=1)

		frappe.set_user(stranger)
		self.assertFalse(frappe.has_permission(REQUEST, "read", doc=out["request"]))
		self.assertEqual(frappe.get_list(REQUEST, fields=["name"]), [])

	def test_the_requester_can_see_their_own_request(self):
		requester = self._plain_user("f")
		self._process("one", "a")
		frappe.set_user(requester)
		out = apply_doctype(self._ir(extra=True), confirm=1)

		self.assertTrue(frappe.has_permission(REQUEST, "read", doc=out["request"]))
		self.assertEqual([r.name for r in frappe.get_list(REQUEST, fields=["name"])], [out["request"]])

	# ── who may use Docu at all ────────────────────────────────────────────
	def test_a_process_owner_without_an_admitted_role_may_change_forms(self):
		owner = self._plain_user("g")
		self._process("one", "g")
		frappe.set_user(owner)

		self.assertTrue(can_change_forms())

	def test_a_person_who_owns_no_process_is_still_refused(self):
		stranger = self._plain_user("h")
		self._process("one", "a")
		frappe.set_user(stranger)

		self.assertFalse(can_change_forms())

	def test_a_plain_process_owner_applies_a_change_to_their_listed_doctype(self):
		owner = self._plain_user("i")
		self._process("one", "i")
		frappe.set_user(owner)
		out = apply_doctype(self._ir(extra=True), confirm=1)

		self.assertEqual(out["status"], "applied")
		self.assertTrue(self._has_extra())

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
