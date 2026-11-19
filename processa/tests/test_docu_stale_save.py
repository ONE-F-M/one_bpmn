"""A Docu save made from an out-of-date copy cannot overwrite a newer edit to the form."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.docu import apply_doctype, get_doctype_schema


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
		return json.dumps(
			{"doctype_name": self.doctype, "app": "processa", "module": "Processa Engine", "fields": fields}
		)

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


class TestDocuEditsBuildOnEachOther(TestDocuStaleSave):
	def _live(self) -> dict:
		return get_doctype_schema(self.doctype)["doctype_ir"]

	def _add(self, ir: dict, *fields) -> str:
		return json.dumps({**ir, "fields": ir["fields"] + list(fields)})

	def _fieldnames(self) -> list:
		return [f.fieldname for f in frappe.get_meta(self.doctype, cached=False).fields]

	def test_a_second_request_keeps_what_the_first_added(self):
		apply_doctype(
			self._add(self._live(), {"fieldname": "phone", "fieldtype": "Data", "label": "Phone"}), confirm=1
		)
		apply_doctype(
			self._add(self._live(), {"fieldname": "email", "fieldtype": "Data", "label": "Email"}), confirm=1
		)

		self.assertEqual(self._fieldnames(), ["title", "phone", "email"])

	def test_a_section_keeps_its_name_when_a_later_save_sends_it_without_one(self):
		section = {"fieldname": "", "fieldtype": "Section Break", "label": "Contact"}
		apply_doctype(
			self._add(self._live(), section, {"fieldname": "phone", "fieldtype": "Data", "label": "Phone"}),
			confirm=1,
		)
		first = self._fieldnames()[1]

		ir = self._live()
		for field in ir["fields"]:
			if field["fieldtype"] == "Section Break":
				field["fieldname"] = ""
		apply_doctype(self._add(ir, {"fieldname": "email", "fieldtype": "Data", "label": "Email"}), confirm=1)

		self.assertEqual(self._fieldnames(), ["title", first, "phone", "email"])
