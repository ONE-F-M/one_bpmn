# Copyright (c) 2026, one-fm and contributors
"""The error report: rate over time, codes, one issue per code and element, and the issue drill-down.

Every test uses its own model, bpmn_ids and error codes, so rows other suites leave behind cannot
change the counts being asserted.

	bench run-tests --skip-before-tests --module one_bpmn.tests.test_insights_errors
"""

from __future__ import annotations

import csv
import io

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.insights_api import export_error_report, get_error_report, get_issue_runs

FROM, TO = "2026-09-01", "2026-09-07"


class TestErrorReport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.maps = []
		for _index in range(2):
			suffix = frappe.generate_hash(length=6)
			cls.maps.append(
				frappe.get_doc(
					{
						"doctype": "BPMN Process Model",
						"title": f"_Test Errors {suffix}",
						"process_id": f"_err_{suffix}",
						"version": 1,
					}
				)
				.insert()
				.name
			)

	def setUp(self):
		frappe.set_user("Administrator")
		tag = frappe.generate_hash(length=6)
		self.model = f"err-model-{tag}"
		self.element = f"err_task_{tag}"
		self.code = lambda name: f"{name}_{tag}"

	def _run(self, day, status="Success", code=None, element=None, process_model=None, **extra):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": element or self.element,
				"bpmn_label": "Error probe",
				"process_model": process_model or self.maps[0],
				"model": self.model,
				"status": status,
				"error_code": code,
				"started_at": f"{day} 10:00:00",
				**extra,
			}
		).insert()

	def _report(self, **kwargs):
		return get_error_report(from_date=FROM, to_date=TO, model=self.model, **kwargs)

	def test_timeseries_has_a_bucket_per_day_and_a_dataset_per_code(self):
		for day in range(1, 8):
			self._run(f"2026-09-0{day}")
		for name, day in (("A", 1), ("B", 2), ("C", 2)):
			self._run(f"2026-09-0{day}", "Error", self.code(name))

		series = self._report()["timeseries"]

		self.assertEqual(series["labels"][0], "2026-09-01")
		self.assertEqual(len(series["labels"]), 7)
		self.assertEqual(len(series["error_rate"]), 7)
		self.assertEqual(series["error_rate"][0], 50.0)
		self.assertEqual(series["error_rate"][1], 66.7)
		self.assertEqual(series["error_rate"][6], 0.0)
		self.assertEqual(
			{d["error_code"] for d in series["by_code"]}, {self.code("A"), self.code("B"), self.code("C")}
		)

	def test_codes_are_sorted_by_count_and_new_codes_are_marked(self):
		self._run("2026-08-15", "Error", self.code("OLD"))
		self._run("2026-09-02", "Error", self.code("OLD"))
		for _index in range(3):
			self._run("2026-09-03", "Error", self.code("NEW"))

		codes = self._report()["codes"]

		self.assertEqual([c["error_code"] for c in codes], [self.code("NEW"), self.code("OLD")])
		self.assertEqual([c["count"] for c in codes], [3, 1])
		self.assertEqual([c["is_new"] for c in codes], [True, False])

	def test_issues_split_by_code_element_and_process(self):
		other = f"{self.element}_other"
		self._run("2026-09-02", "Error", self.code("X"))
		self._run("2026-09-03")
		self._run("2026-09-02", "Error", self.code("X"), element=other)
		self._run("2026-09-02", "Error", self.code("X"), process_model=self.maps[1])
		self._run("2026-08-10", "Error", self.code("X"))

		issues = self._report()["issues"]

		self.assertEqual(len(issues), 3)
		first = next(i for i in issues if i["bpmn_id"] == self.element and i["process_model"] == self.maps[0])
		self.assertEqual((first["errors"], first["runs"], first["error_rate"]), (1, 2, 50.0))
		self.assertEqual(first["first_seen"][:10], "2026-08-10")
		self.assertEqual(first["last_seen"][:10], "2026-09-02")
		self.assertFalse(first["is_new"])
		self.assertEqual(first["key"], f"{self.code('X')}|{self.element}|{self.maps[0]}|{self.model}")

	def test_retried_runs_and_recovery_come_from_counts(self):
		for index in range(31):
			status = "Success" if index < 19 else "Error"
			self._run("2026-09-04", status, None if status == "Success" else self.code("R"), retry_count=1)

		summary = self._report()["summary"]

		self.assertEqual((summary["retried"], summary["retry_recovered"]), (31, 19))
		self.assertEqual(summary["retry_recovery_rate"], 61.3)

	def test_suspended_runs_are_counted_apart_from_the_error_rate(self):
		self._run("2026-09-05")
		self._run("2026-09-05", "Error", self.code("S"))
		for _index in range(7):
			self._run("2026-09-05", "Suspended")

		summary = self._report()["summary"]

		self.assertEqual(summary["suspended"], 7)
		self.assertEqual(summary["runs"], 2)
		self.assertEqual(summary["error_rate"], 50.0)

	def test_error_code_filter_narrows_issues_only(self):
		self._run("2026-09-02")
		self._run("2026-09-02", "Error", self.code("TIMEOUT"))
		self._run("2026-09-02", "Error", self.code("OTHER"))

		report = self._report(error_code=self.code("TIMEOUT"))

		self.assertEqual([i["error_code"] for i in report["issues"]], [self.code("TIMEOUT")])
		self.assertEqual(report["issues"][0]["error_rate"], 33.3)
		self.assertEqual(report["summary"]["errors"], 2)
		self.assertEqual(len(report["codes"]), 2)

	def test_previous_period_fills_the_deltas(self):
		self._run("2026-08-28")
		self._run("2026-08-28", "Error", self.code("P"))
		self._run("2026-09-02")
		self._run("2026-09-02")
		self._run("2026-09-02")
		self._run("2026-09-02", "Error", self.code("P"))

		report = self._report()

		self.assertEqual(report["summary"]["previous_error_rate"], 50.0)
		self.assertEqual(report["summary"]["previous_errors"], 1)
		self.assertEqual(report["summary"]["delta_pt"], -25.0)
		self.assertEqual(report["summary"]["errors_delta"], 0.0)
		self.assertEqual(report["issues"][0]["delta_pt"], -25.0)
		self.assertEqual(report["previous_to"], "2026-08-31")

	def test_retry_recovery_delta_is_in_points(self):
		self._run("2026-08-28", "Success", retry_count=1)
		self._run("2026-08-28", "Error", self.code("Q"), retry_count=1)
		self._run("2026-09-02", "Success", retry_count=1)

		summary = self._report()["summary"]

		self.assertEqual(summary["retry_recovery_rate"], 100.0)
		self.assertEqual(summary["retry_recovery_delta_pt"], 50.0)
		self.assertEqual(summary["errors_delta"], -100.0)

	def test_no_previous_runs_leaves_the_delta_empty(self):
		self._run("2026-09-02", "Error", self.code("N"))

		report = self._report()

		self.assertIsNone(report["summary"]["delta_pt"])
		self.assertIsNone(report["summary"]["errors_delta"])
		self.assertIsNone(report["summary"]["retry_recovery_delta_pt"])
		self.assertIsNone(report["summary"]["previous_error_rate"])
		self.assertIsNone(report["issues"][0]["delta_pt"])

	def test_p95_duration_covers_the_counted_runs_of_the_element(self):
		for duration in range(100, 2100, 100):
			self._run("2026-09-03", duration_ms=duration)
		self._run("2026-09-03", "Error", self.code("D"), duration_ms=5000)

		issue = self._report()["issues"][0]

		self.assertEqual(issue["runs"], 21)
		self.assertEqual(issue["p95_duration_ms"], 2000)

	def test_issue_runs_page_the_latest_failed_top_level_runs(self):
		parent = None
		for day in range(1, 6):
			parent = self._run(
				f"2026-09-0{day}", "Error", self.code("I"), error_message="x" * 300, duration_ms=day
			)
		self._run("2026-09-06", "Error", self.code("I"), parent_run=parent.name)
		key = self._report()["issues"][0]["key"]

		first = get_issue_runs(key, FROM, TO, limit=3)
		second = get_issue_runs(key, FROM, TO, limit=3, offset=3)

		self.assertEqual(first["total"], 5)
		self.assertEqual([r["duration_ms"] for r in first["runs"]], [5, 4, 3])
		self.assertEqual([r["duration_ms"] for r in second["runs"]], [2, 1])
		self.assertEqual(len(first["runs"][0]["error_message"]), 200)

	def test_a_malformed_issue_key_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			get_issue_runs("only|three|parts", FROM, TO)

	def test_the_legacy_keys_are_gone(self):
		self._run("2026-09-02", "Error", self.code("L"))

		report = self._report()

		self.assertNotIn("rows", report)
		self.assertNotIn("error_breakdown", report)
		for key in ("total_errors", "most_common_error", "worst_element"):
			self.assertNotIn(key, report["summary"])

	def test_export_writes_one_row_per_issue(self):
		self._run("2026-09-02", "Error", self.code("E1"))
		self._run("2026-09-02", "Error", self.code("E2"))

		export_error_report(from_date=FROM, to_date=TO, model=self.model)

		self.assertEqual(frappe.response["type"], "binary")
		self.assertEqual(frappe.response["filename"], f"errors-model-{FROM}-to-{TO}.csv")
		rows = list(csv.reader(io.StringIO(frappe.response["filecontent"].decode("utf-8-sig"))))
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0][0], "Error type")

	def test_a_user_without_system_manager_is_refused(self):
		email = f"err-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Errors", "send_welcome_email": 0}
		).insert()
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		frappe.set_user(email)

		# frappe.only_for is a no-op while in_test is set, so the guard cannot fire unless it is cleared.
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				get_error_report(from_date=FROM, to_date=TO)
			with self.assertRaises(frappe.PermissionError):
				get_issue_runs("a|b|c|d", FROM, TO)
		finally:
			frappe.flags.in_test = True
