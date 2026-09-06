# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Applying a design with a different module actually moves the DocType."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import apply_doctype


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
		return json.dumps({"doctype_name": self.name, "module": module, "fields": fields})

	def test_a_new_doctype_lands_in_the_module_it_asked_for(self):
		apply_doctype(self._ir("ONE BPMN"), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "ONE BPMN")

	def test_applying_a_different_module_moves_it(self):
		apply_doctype(self._ir("ONE BPMN"), confirm=1)
		apply_doctype(self._ir("Operations"), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "Operations")

	def test_a_child_table_follows_its_parent(self):
		"""Left behind, it is the same bug one level down — and the child ends up
		orphaned in a module its parent no longer belongs to."""
		apply_doctype(self._ir("ONE BPMN", with_child=True), confirm=1)
		child = frappe.db.get_value("DocType", {"name": ["like", f"{self.name}%"], "istable": 1}, "name")
		self.assertTrue(child, "no child table was created")
		self.made.append(child)

		apply_doctype(self._ir("Operations", with_child=True), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "Operations")
		self.assertEqual(frappe.db.get_value("DocType", child, "module"), "Operations")

	def test_an_unrecognised_module_still_falls_back(self):
		apply_doctype(self._ir("Not A Real Module"), confirm=1)
		self.assertEqual(frappe.db.get_value("DocType", self.name, "module"), "ONE BPMN")
