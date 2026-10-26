# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Docu handles a field change Customize Form refuses instead of losing the whole save behind it."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import _docu_user, apply_doctype
from one_bpmn.security.doctype_validator import validate_doctype_ir

DOCTYPE = "ToDo"
FIELDNAME = "docu_refused_change_date"


def _ir(*fields) -> str:
	return frappe.as_json({"doctype_name": DOCTYPE, "fields": list(fields)})


def _date_field(fieldtype: str = "Date") -> dict:
	return {"fieldname": FIELDNAME, "label": "Docu Refused Change Date", "fieldtype": fieldtype}


class TestRefusedTypeChange(FrappeTestCase):
	"""Creating and deleting a Custom Field runs ALTER TABLE, which commits, so each test cleans up itself."""

	def setUp(self):
		self._drop_field()
		create_custom_fields({DOCTYPE: [{**_date_field("Data"), "insert_after": "description"}]})
		frappe.db.set_value("Custom Field", {"dt": DOCTYPE, "fieldname": FIELDNAME}, "owner", _docu_user())
		frappe.db.commit()
		frappe.clear_cache(doctype=DOCTYPE)

	def tearDown(self):
		frappe.db.rollback()
		self._drop_field()

	def _drop_field(self):
		name = frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": FIELDNAME})
		if name:
			frappe.delete_doc("Custom Field", name)
			frappe.db.commit()
		frappe.clear_cache(doctype=DOCTYPE)

	def test_an_empty_docu_field_is_recreated_with_the_new_type(self):
		apply_doctype(_ir(_date_field("Date")), confirm=1)

		frappe.clear_cache(doctype=DOCTYPE)
		self.assertEqual(frappe.get_meta(DOCTYPE).get_field(FIELDNAME).fieldtype, "Date")

	def test_a_field_holding_data_is_refused_in_plain_words(self):
		todo = frappe.get_doc(
			{"doctype": DOCTYPE, "description": "Docu refused change", "allocated_to": "Administrator"}
		).insert()
		frappe.db.set_value(DOCTYPE, todo.name, FIELDNAME, "10 Oct")

		with self.assertRaises(frappe.ValidationError) as refused:
			apply_doctype(_ir(_date_field("Date")), confirm=1)

		message = str(refused.exception)
		self.assertIn("is a Data field and cannot become Date", message)
		self.assertIn("Select", message)
		self.assertNotIn("Traceback", message)
		self.assertEqual(frappe.get_meta(DOCTYPE).get_field(FIELDNAME).fieldtype, "Data")


class TestNoParallelField(FrappeTestCase):
	def tearDown(self):
		# A field created by mistake commits its ALTER TABLE, so it is removed explicitly.
		name = frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": "docu_second_description"})
		if name:
			frappe.delete_doc("Custom Field", name)
			frappe.db.commit()

	def test_a_new_field_with_an_existing_label_is_not_created(self):
		result = apply_doctype(
			_ir({"fieldname": "docu_second_description", "label": "Description", "fieldtype": "Data"}), confirm=1
		)

		self.assertFalse(frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": "docu_second_description"}))
		self.assertEqual(len(result["notes"]), 1)
		self.assertIn("(description)", result["notes"][0])


class TestFetchFromIsChecked(FrappeTestCase):
	def _violations(self, fetch_from: str) -> list:
		field = {"fieldname": "assignee_name", "label": "Assignee Name", "fieldtype": "Data", "fetch_from": fetch_from}
		return validate_doctype_ir({"doctype_name": DOCTYPE, "fields": [field]})["violations"]

	def test_a_target_field_the_linked_doctype_lacks_is_rejected(self):
		violations = self._violations("allocated_to.relieving_date")

		self.assertEqual(len(violations), 1)
		self.assertIn("'Assignee Name'", violations[0])
		self.assertIn("User does not have", violations[0])

	def test_a_space_in_the_fetch_from_is_rejected(self):
		self.assertIn("no spaces", self._violations("allocated_to.full _name")[0])

	def test_a_real_target_field_passes(self):
		self.assertEqual(self._violations("allocated_to.full_name"), [])
