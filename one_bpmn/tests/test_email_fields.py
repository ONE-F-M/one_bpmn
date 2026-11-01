"""Tests for get_email_fields and the email field builders.

The Leave Application cases need HRMS and one_fm's Arabic Employee fields, so they skip on a site without them.

Run with: bench run-tests --app one_bpmn --module one_bpmn.tests.test_email_fields
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.api.utils import get_email_fields
from one_bpmn.email_builder.fields import build_field_rows, build_kick, default_fact_fields
from one_bpmn.utils.translation import translate_cached

EMPLOYEE = {
	"employee_name": "Fatima Hassan",
	"employee_name_in_arabic": "فاطمة حسن",
	"department": "Operations - ONEFM",
}


def _has_leave_setup() -> bool:
	return bool(
		frappe.db.exists("DocType", "Leave Application")
		and frappe.get_meta("Employee").get_field("employee_name_in_arabic")
	)


def _leave_application():
	return frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": "HR-EMP-TEST-1",
			"employee_name": "Fatima Hassan",
			"leave_type": "Annual Leave",
			"from_date": "2026-10-05",
			"to_date": "2026-10-07",
			"total_leave_days": 3,
			"status": "Open",
		}
	)


def _employee_reads():
	real_get_value = frappe.db.get_value

	def get_value(doctype, name=None, fieldname=None, *args, **kwargs):
		if doctype == "Employee" and name == "HR-EMP-TEST-1":
			return EMPLOYEE.get(fieldname)
		return real_get_value(doctype, name, fieldname, *args, **kwargs)

	return patch.object(frappe.db, "get_value", side_effect=get_value)


def _row(rows, label):
	return next(r for r in rows if r["label"]["en"] == label)


class TestEmailFieldsOnToDo(FrappeTestCase):
	"""ToDo ships with Frappe, so these run on any site."""

	def setUp(self):
		clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_endpoint_lists_own_and_linked_fields_without_layout_fields(self):
		result = get_email_fields("ToDo")
		own = {f["fieldname"]: f for f in result["fields"]}
		self.assertIn("description", own)
		self.assertIn("date", own)
		self.assertNotIn("section_break_6", own)
		self.assertFalse(
			{"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table"}
			& {f["fieldtype"] for f in result["fields"]}
		)
		group = next(g for g in result["linked"] if g["link_field"] == "allocated_to")
		self.assertEqual(group["doctype"], "User")
		self.assertIn("allocated_to.full_name", [f["fieldname"] for f in group["fields"]])

	def test_needs_arabic_by_field_type(self):
		own = {f["fieldname"]: f for f in get_email_fields("ToDo")["fields"]}
		self.assertTrue(own["description"]["needs_arabic"])
		for fieldname in ("date", "status", "priority"):
			self.assertFalse(own[fieldname]["needs_arabic"], fieldname)
			self.assertEqual(own[fieldname]["arabic_candidates"], [])

	def test_no_candidates_is_an_empty_list(self):
		own = {f["fieldname"]: f for f in get_email_fields("ToDo")["fields"]}
		self.assertEqual(own["description"]["arabic_candidates"], [])

	def test_user_without_read_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_email_fields("ToDo")

	def test_rows_format_by_type_and_translate_labels_and_select(self):
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "<p>Check the <b>report</b></p>",
				"status": "Cancelled",
				"date": "2026-10-05",
			}
		)
		rows = build_field_rows(todo, ["description", "status", "date"])
		self.assertEqual(
			_row(rows, "Description")["value"], {"en": "Check the report", "ar": "Check the report"}
		)
		status = _row(rows, "Status")
		self.assertEqual(status["value"]["en"], "Cancelled")
		self.assertEqual(status["value"]["ar"], frappe._("Cancelled", lang="ar"))
		self.assertEqual(status["label"]["ar"], frappe._("Status", lang="ar"))
		self.assertEqual(_row(rows, "Due Date")["value"]["en"], frappe.utils.formatdate("2026-10-05"))

	def test_select_ignores_a_paired_arabic_field(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "x", "status": "Open"})
		rows = build_field_rows(todo, [["status", "description"]])
		self.assertEqual(rows[0]["value"]["ar"], frappe._("Open", lang="ar"))

	def test_missing_field_is_skipped_and_logged(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "x", "status": "Open"})
		with patch("frappe.log_error") as log_error:
			rows = build_field_rows(todo, ["no_such_field", "allocated_to.no_such_field", "status"])
		self.assertEqual([r["label"]["en"] for r in rows], ["Status"])
		self.assertEqual(log_error.call_count, 2)
		self.assertIn("no_such_field", log_error.call_args_list[0].kwargs["message"])

	def test_default_facts_are_list_view_then_mandatory_in_form_order(self):
		meta = frappe.get_meta("ToDo")
		expected = [df.fieldname for df in meta.fields if df.in_list_view]
		expected += [df.fieldname for df in meta.fields if df.reqd and df.fieldname not in expected]
		self.assertEqual(default_fact_fields("ToDo"), expected[:6])
		self.assertLessEqual(len(default_fact_fields("ToDo")), 6)

	def test_kick_in_both_languages(self):
		translate_cached.clear_cache()
		with patch("one_bpmn.utils.translation.translate_cached", return_value="مراجعة"):
			kick = build_kick("ToDo", "Review")
		self.assertEqual(kick["en"], "ToDo · Review")
		self.assertEqual(kick["ar"], f"{frappe._('ToDo', lang='ar')} · مراجعة")

	def test_kick_falls_back_to_the_english_task_name_and_logs(self):
		translate_cached.clear_cache()
		with (
			patch("one_bpmn.utils.translation.GoogleTranslator", side_effect=ConnectionError("blocked")),
			patch("one_bpmn.utils.translation.MyMemoryTranslator", side_effect=ConnectionError("blocked")),
			patch("frappe.log_error") as log_error,
		):
			kick = build_kick("ToDo", "Final approval")
		self.assertTrue(kick["ar"].endswith("· Final approval"))
		log_error.assert_called()


@unittest.skipUnless(_has_leave_setup(), "needs HRMS and one_fm's Arabic Employee fields")
class TestEmailFieldsOnLeaveApplication(FrappeTestCase):
	def setUp(self):
		clear_cache()

	def test_candidates_include_the_employee_arabic_names(self):
		result = get_email_fields("Leave Application")
		own = {f["fieldname"]: f for f in result["fields"]}
		candidates = own["employee_name"]["arabic_candidates"]
		for fieldname in (
			"employee.employee_name_in_arabic",
			"employee.one_fm_first_name_in_arabic",
			"employee.one_fm_last_name_in_arabic",
		):
			self.assertIn(fieldname, candidates)
		self.assertEqual(own["from_date"]["arabic_candidates"], [])

	def test_rows_for_leave_application(self):
		fields = [
			"employee_name",
			"leave_type",
			"from_date",
			"to_date",
			"total_leave_days",
			"employee.department",
		]
		with _employee_reads():
			rows = build_field_rows(_leave_application(), fields)
		self.assertEqual(len(rows), 6)
		self.assertEqual(_row(rows, "Employee Name")["label"]["ar"], frappe._("Employee Name", lang="ar"))
		self.assertEqual(_row(rows, "Employee Name")["value"], {"en": "Fatima Hassan", "ar": "Fatima Hassan"})
		self.assertEqual(_row(rows, "Department")["value"]["en"], "Operations - ONEFM")
		self.assertEqual(_row(rows, "From Date")["value"]["en"], frappe.utils.formatdate("2026-10-05"))

	def test_paired_arabic_field_fills_the_arabic_value(self):
		with _employee_reads():
			rows = build_field_rows(
				_leave_application(), [["employee_name", "employee.employee_name_in_arabic"]]
			)
		self.assertEqual(rows[0]["value"], {"en": "Fatima Hassan", "ar": "فاطمة حسن"})

	def test_empty_arabic_field_shows_the_english_value(self):
		with _employee_reads(), patch.dict(EMPLOYEE, {"employee_name_in_arabic": ""}):
			rows = build_field_rows(
				_leave_application(), [["employee_name", "employee.employee_name_in_arabic"]]
			)
		self.assertEqual(rows[0]["value"]["ar"], "Fatima Hassan")

	def test_date_ignores_a_paired_arabic_field(self):
		with _employee_reads():
			rows = build_field_rows(_leave_application(), [["from_date", "employee.employee_name_in_arabic"]])
		self.assertNotEqual(rows[0]["value"]["ar"], "فاطمة حسن")
