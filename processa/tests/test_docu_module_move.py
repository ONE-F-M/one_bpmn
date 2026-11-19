# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A new DocType lands only in the app and module picked for it, and a module change moves it."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.docu import apply_doctype, list_apps, list_modules


class TestModuleMove(FrappeTestCase):
	"""The module used to be honoured on CREATE and ignored on every update, so
	a user who asked to move a form saw the panel change, saw the agent agree,
	and found the DocType exactly where it was."""

	def setUp(self):
		# The name validator allows letters, digits and single spaces only, and
		# must start with a letter — no leading underscore, so the usual _Test
		# prefix cannot be used here.
		self.name = "Zz Move Probe " + frappe.generate_hash(length=6).upper()
		self.child = f"{self.name} Rows Item"
		self.made = [self.name, self.child]

	def tearDown(self):
		for n in self.made:
			if frappe.db.exists("DocType", n):
				frappe.delete_doc("DocType", n, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _ir(self, module, with_child=False):
		fields = [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}]
		if with_child:
			fields.append({
				"fieldname": "rows", "fieldtype": "Table", "label": "Rows",
				"child_fields": [{"fieldname": "note", "fieldtype": "Data", "label": "Note"}],
			})
		app = frappe.db.get_value("Module Def", module, "app_name") or "processa"
		return json.dumps({"doctype_name": self.name, "app": app, "module": module, "fields": fields})

	def test_a_new_doctype_lands_in_the_module_it_asked_for(self):
		apply_doctype(self._ir("Processa Engine"), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "Processa Engine")

	def test_applying_a_different_module_moves_it(self):
		apply_doctype(self._ir("Processa Engine"), confirm=1)
		apply_doctype(self._ir("Operations"), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "Operations")

	def test_a_child_table_follows_its_parent(self):
		"""Left behind, it is the same bug one level down — and the child ends up
		orphaned in a module its parent no longer belongs to."""
		apply_doctype(self._ir("Processa Engine", with_child=True), confirm=1)
		child = frappe.db.get_value("DocType", {"name": ["like", f"{self.name}%"], "istable": 1}, "name")
		self.assertTrue(child, "no child table was created")
		self.made.append(child)

		apply_doctype(self._ir("Operations", with_child=True), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "Operations")
		self.assertEqual(frappe.db.get_value("DocType", child, "module"), "Operations")

	def test_a_new_doctype_without_an_app_and_module_asks_for_them(self):
		ir = json.dumps(
			{
				"doctype_name": self.name,
				"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
			}
		)

		result = apply_doctype(ir, confirm=1)

		self.assertEqual(result["status"], "needs_placement")
		self.assertFalse(frappe.db.exists("DocType", self.name))

	def test_a_module_outside_the_picked_app_is_refused(self):
		ir = json.loads(self._ir("Operations"))
		ir["app"] = "processa"

		with self.assertRaises(frappe.ValidationError):
			apply_doctype(json.dumps(ir), confirm=1)
		self.assertFalse(frappe.db.exists("DocType", self.name))

	def test_an_unrecognised_module_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			apply_doctype(self._ir("Not A Real Module"), confirm=1)
		self.assertFalse(frappe.db.exists("DocType", self.name))

	def test_an_update_naming_no_app_keeps_the_module(self):
		apply_doctype(self._ir("Operations"), confirm=1)
		ir = {"doctype_name": self.name, "fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}]}

		apply_doctype(json.dumps(ir), confirm=1)

		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "Operations")

	def test_the_pickers_list_apps_and_only_the_picked_apps_modules(self):
		self.assertIn("processa", list_apps())
		modules = list_modules("processa")
		self.assertIn({"name": "Processa Engine", "app": "processa"}, modules)
		self.assertEqual({m["app"] for m in modules}, {"processa"})

	def test_a_guest_cannot_list_apps(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				list_apps()
		finally:
			frappe.set_user("Administrator")
