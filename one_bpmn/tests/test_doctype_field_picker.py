# Copyright (c) 2026, one-fm and contributors
"""The field autocompletes in the BPMN properties panel.

``get_doctype_fields`` backs every field picker on a Service or User Task. It
read the DocField table, where Custom Fields do not live — so on a doctype this
site customises (Task's assignee table, a Department's approvers) the picker was
empty and the property could not be set at all. That is what stopped a User Task
being assigned to a multi-select of users.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_doctype_field_picker
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.utils import get_doctype_fields

TABLES = '["Table MultiSelect","Table"]'


class TestDoctypeFieldPicker(FrappeTestCase):
	def _names(self, doctype, **kwargs):
		return [f["fieldname"] for f in get_doctype_fields(doctype, **kwargs)]

	def _custom_user_table(self):
		"""A multi-select of users added by customisation — the shape this site
		actually uses for "any of these people may action it"."""
		name = "ToDo-custom_test_actioners"
		# A Custom Field insert commits, so it outlives a rolled-back test run:
		# clear it going in as well as coming out.
		self._drop(name)
		field = frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "ToDo",
			"fieldname": "custom_test_actioners",
			"label": "Actioners",
			"fieldtype": "Table MultiSelect",
			"options": "Assignment Rule User",
		}).insert(ignore_permissions=True)
		self.addCleanup(self._drop, name)
		frappe.clear_cache(doctype="ToDo")
		return field

	def _drop(self, name):
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
			frappe.db.commit()
		frappe.clear_cache(doctype="ToDo")

	def test_a_custom_table_field_can_be_picked(self):
		self._custom_user_table()
		self.assertIn("custom_test_actioners", self._names("ToDo", fieldtype_in=TABLES))

	def test_the_row_user_field_can_be_picked_after_it(self):
		"""The panel chains two lookups: the table field names a child doctype,
		and the child's User link is what each row is read through. Both halves
		have to come back or the mode cannot be configured."""
		self._custom_user_table()

		tables = get_doctype_fields("ToDo", fieldtype_in=TABLES, include_options=True)
		child = next(f["options"] for f in tables if f["fieldname"] == "custom_test_actioners")

		rows = get_doctype_fields(child, fieldtype_in='["Link"]', include_options=True)
		self.assertIn("user", [f["fieldname"] for f in rows if f["options"] == "User"])

	def test_standard_fields_are_still_returned(self):
		names = self._names("ToDo")
		self.assertIn("description", names)
		self.assertIn("allocated_to", names)

	def test_the_fieldtype_filter_is_honoured(self):
		for field in get_doctype_fields("ToDo", fieldtype_in='["Link"]'):
			self.assertEqual(field["fieldtype"], "Link")

	def test_layout_fields_are_left_out_by_default(self):
		types = {f["fieldtype"] for f in get_doctype_fields("ToDo")}
		self.assertFalse(types & {"Section Break", "Column Break", "Tab Break", "Table"})

	def test_the_exclusion_filter_is_honoured(self):
		self.assertNotIn(
			"Link",
			{f["fieldtype"] for f in get_doctype_fields("ToDo", fieldtype_not_in='["Link"]')},
		)

	def test_search_filters_on_fieldname(self):
		names = self._names("ToDo", search_text="allocated")
		self.assertIn("allocated_to", names)
		self.assertNotIn("description", names)

	def test_a_missing_doctype_is_empty_not_an_error(self):
		"""The panel asks before a doctype has necessarily been chosen."""
		self.assertEqual(get_doctype_fields(""), [])
		self.assertEqual(get_doctype_fields("No Such DocType At All"), [])

	def test_bad_filter_json_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			get_doctype_fields("ToDo", fieldtype_in="not json")
