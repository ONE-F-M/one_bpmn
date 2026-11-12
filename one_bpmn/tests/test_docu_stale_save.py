"""A Docu save made from an out-of-date copy cannot overwrite a newer edit to the form."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu import apply_doctype, get_doctype_schema


class TestDocuStaleSave(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.doctype = "Zz Stale Probe " + frappe.generate_hash(length=6).upper()
		apply_doctype(self._ir(), confirm=1)

	def tearDown(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("DocType", self.doctype):
			frappe.delete_doc("DocType", self.doctype, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _ir(self):
		fields = [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}]
		return json.dumps({"doctype_name": self.doctype, "module": "ONE BPMN", "fields": fields})

	def _edit_in_desk(self):
		doc = frappe.get_doc("DocType", self.doctype)
		doc.append("fields", {"fieldname": "extra", "fieldtype": "Data", "label": "Extra"})
		doc.save(ignore_permissions=True)

	def _has_extra(self):
		return bool(frappe.db.exists("DocField", {"parent": self.doctype, "fieldname": "extra"}))

	def test_stale_copy_is_refused_and_the_edit_survives(self):
		base = get_doctype_schema(self.doctype)["modified"]
		self._edit_in_desk()
		with self.assertRaises(frappe.ValidationError):
			apply_doctype(self._ir(), confirm=1, base_modified=base)
		self.assertTrue(self._has_extra())

	def test_current_copy_saves_and_returns_the_next_base(self):
		base = get_doctype_schema(self.doctype)["modified"]
		first = apply_doctype(self._ir(), confirm=1, base_modified=base)
		second = apply_doctype(self._ir(), confirm=1, base_modified=first["modified"])
		self.assertEqual(second["action"], "updated")

	def test_a_save_without_a_base_still_replaces_the_form(self):
		self._edit_in_desk()
		apply_doctype(self._ir(), confirm=1)
		self.assertFalse(self._has_extra())
