# Copyright (c) 2026, one-fm and contributors
"""What a BPMN condition can see of the context document.

Two defects, both of which halted the Visa process in production:

  * the mid-run refresh copied the ROOT workflow data — the snapshot taken when
    the instance started — so a Service Task that moved the document on never
    reached the gateway that tested it;
  * the field filter kept only str/int/float/bool, silently dropping every Date,
    Datetime, Time and Currency field, so a gateway testing one of those raised
    NameError and was read as False.
"""

from __future__ import annotations

import datetime
import decimal

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.engine import json_safe_doc_fields


class _Field:
	def __init__(self, fieldname):
		self.fieldname = fieldname


class _Meta:
	def __init__(self, names):
		self.fields = [_Field(n) for n in names]


class _Doc:
	"""The narrow slice of a Document that json_safe_doc_fields touches."""

	def __init__(self, values, docstatus=0):
		self._values = values
		self.meta = _Meta(list(values))
		self.docstatus = docstatus

	def get(self, fieldname):
		return self._values.get(fieldname)


class TestJSONSafeDocFields(FrappeTestCase):
	def test_dates_are_converted_not_dropped(self):
		"""A Date/Datetime/Time field must reach the condition, not vanish.

		Dropping them is what made ``visa_issue_date and visa_expiry_date``
		unsatisfiable no matter what the document held.
		"""
		out = json_safe_doc_fields(
			_Doc(
				{
					"issue": datetime.date(2026, 8, 1),
					"stamped": datetime.datetime(2026, 8, 1, 10, 30),
					"at": datetime.time(9, 15),
				}
			)
		)
		self.assertEqual(out["issue"], "2026-08-01")
		self.assertEqual(out["stamped"], "2026-08-01T10:30:00")
		self.assertEqual(out["at"], "09:15:00")
		# and the point of converting them: they are truthy
		self.assertTrue(out["issue"] and out["stamped"] and out["at"])

	def test_currency_becomes_a_number(self):
		out = json_safe_doc_fields(_Doc({"fee": decimal.Decimal("12.50")}))
		self.assertEqual(out["fee"], 12.5)
		self.assertIsInstance(out["fee"], float)

	def test_plain_scalars_and_none_survive_unchanged(self):
		out = json_safe_doc_fields(
			_Doc({"s": "x", "i": 3, "f": 1.5, "b": True, "n": None})
		)
		self.assertEqual(
			{k: out[k] for k in ("s", "i", "f", "b", "n")},
			{"s": "x", "i": 3, "f": 1.5, "b": True, "n": None},
		)

	def test_child_tables_are_still_skipped(self):
		"""Not serialisable and not testable — they must not leak into task data."""
		out = json_safe_doc_fields(_Doc({"rows": [{"a": 1}], "keep": "yes"}))
		self.assertNotIn("rows", out)
		self.assertIn("keep", out)

	def test_docstatus_is_always_present_as_an_int(self):
		"""Conditions test ``docstatus`` constantly, and it is not in meta.fields."""
		out = json_safe_doc_fields(_Doc({}, docstatus=1))
		self.assertEqual(out["docstatus"], 1)
		self.assertIsInstance(out["docstatus"], int)

	def test_output_is_json_serialisable(self):
		"""The whole reason the filter exists: task data gets serialised."""
		out = json_safe_doc_fields(
			_Doc(
				{
					"d": datetime.date(2026, 1, 1),
					"dt": datetime.datetime(2026, 1, 1, 0, 0),
					"c": decimal.Decimal("1.25"),
					"rows": [{"a": 1}],
				}
			)
		)
		frappe.as_json(out)  # raises if anything non-serialisable got through


class TestRefreshTaskDataFromContext(FrappeTestCase):
	"""The mid-run refresh must read the DOCUMENT, not the start-time snapshot."""

	def test_refresh_picks_up_a_write_made_after_the_instance_started(self):
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "bpmn task-data refresh regression",
				"allocated_to": "Administrator",
			}
		).insert()

		instance = frappe.new_doc("BPMN Process Instance")
		instance.context_doctype = "ToDo"
		instance.context_docname = todo.name

		class _Task:
			data = {"status": "Open"}

		task = _Task()

		# Exactly what a Service Task does: change the document, not task data.
		frappe.db.set_value("ToDo", todo.name, "status", "Closed")

		instance._refresh_task_data_from_context(task)
		self.assertEqual(
			task.data["status"],
			"Closed",
			"the gateway would still be testing the start-time value",
		)

	def test_refresh_without_a_context_document_is_a_no_op(self):
		instance = frappe.new_doc("BPMN Process Instance")
		instance.context_doctype = None
		instance.context_docname = None

		class _Task:
			data = {"untouched": True}

		task = _Task()
		instance._refresh_task_data_from_context(task)
		self.assertEqual(task.data, {"untouched": True})

	def test_refresh_never_raises_when_the_document_is_gone(self):
		"""A failed refresh must not strand a task the user has just completed."""
		instance = frappe.new_doc("BPMN Process Instance")
		instance.context_doctype = "ToDo"
		instance.context_docname = "does-not-exist-at-all"

		class _Task:
			data = {}

		task = _Task()
		instance._refresh_task_data_from_context(task)  # must not raise
