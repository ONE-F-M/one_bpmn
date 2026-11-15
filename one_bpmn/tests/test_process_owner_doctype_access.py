"""A user holding only the Process Owner role can create and modify DocTypes."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.install import grant_process_owner_doctype_access as grant


class TestProcessOwnerDoctypeAccess(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		tag = frappe.generate_hash(length=6)
		self.email = f"zz_po_{tag}@example.com"
		self.doctype = f"Zz Po Probe {tag.upper()}"
		frappe.get_doc({
			"doctype": "User", "email": self.email, "first_name": "Po Only",
			"send_welcome_email": 0, "enabled": 1,
			"roles": [{"role": "Process Owner"}],
		}).insert(ignore_permissions=True)
		frappe.db.delete("DocPerm", {"parent": "DocType", "role": "Process Owner"})
		frappe.clear_cache(doctype="DocType")

	def tearDown(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("DocType", self.doctype):
			frappe.delete_doc("DocType", self.doctype, force=True, ignore_permissions=True)
		frappe.delete_doc("User", self.email, force=True, ignore_permissions=True)

	def _new_doctype(self):
		return frappe.get_doc({
			"doctype": "DocType", "name": self.doctype, "module": "ONE BPMN", "custom": 1,
			"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
			"permissions": [{"role": "System Manager", "read": 1}],
		})

	def test_denied_without_the_grant(self):
		frappe.set_user(self.email)
		self.assertFalse(frappe.has_permission("DocType", "create"))
		with self.assertRaises(frappe.PermissionError):
			self._new_doctype().insert()

	def test_creates_and_modifies_after_the_grant(self):
		grant()
		frappe.set_user(self.email)
		doc = self._new_doctype().insert()
		doc.append("fields", {"fieldname": "notes", "fieldtype": "Data", "label": "Notes"})
		doc.save()
		self.assertTrue(frappe.db.exists("DocField", {"parent": self.doctype, "fieldname": "notes"}))

	def test_delete_is_not_granted(self):
		grant()
		frappe.set_user(self.email)
		self.assertFalse(frappe.has_permission("DocType", "delete"))

	def test_desk_lists_doctype_when_custom_docperm_rows_exist(self):
		frappe.db.delete("Custom DocPerm", {"parent": "DocType", "role": "Process Owner"})
		if not frappe.db.exists("Custom DocPerm", {"parent": "DocType"}):
			self.addCleanup(frappe.db.delete, "Custom DocPerm", {"parent": "DocType", "role": "System Manager"})
			frappe.get_doc({
				"doctype": "Custom DocPerm", "parent": "DocType", "parenttype": "DocType",
				"parentfield": "permissions", "role": "System Manager", "read": 1,
			}).insert(ignore_permissions=True)
		grant()
		rows = frappe.permissions.get_valid_perms("DocType", user=self.email)
		self.assertIn("Process Owner", {row.role for row in rows if row.read and row.create})

	def test_grant_is_idempotent_and_repairs_a_row(self):
		grant()
		frappe.db.set_value("DocPerm", {"parent": "DocType", "role": "Process Owner"}, "create", 0)
		grant()
		rows = frappe.get_all("DocPerm", {"parent": "DocType", "role": "Process Owner"}, ["create"])
		self.assertEqual([r.create for r in rows], [1])
