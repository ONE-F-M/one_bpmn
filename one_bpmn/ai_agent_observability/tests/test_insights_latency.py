# Copyright (c) 2026, one-fm and contributors
"""The latency report: agent-time percentiles per bucket, elements, prior period, time split and export.

Every test uses its own model and bpmn_ids, so rows other suites leave behind cannot change the figures.

	bench run-tests --module one_bpmn.ai_agent_observability.tests.test_insights_latency
"""

from __future__ import annotations

import csv
import io

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from one_bpmn.ai_agent_observability.reports.periods import list_bucket_labels
from one_bpmn.api.insights import export_latency_report, get_performance_report

FROM, TO = "2026-09-01", "2026-09-07"
PRIOR_DAY = "2026-08-28"

ELEMENT_FIELDS = {
	"key",
	"bpmn_id",
	"bpmn_label",
	"process_model",
	"series",
	"runs",
	"measured_runs",
	"error_runs",
	"p50_ms",
	"p95_ms",
	"avg_ms",
	"max_ms",
	"total_ms",
	"avg_steps",
	"human_wait_runs",
	"avg_human_wait_ms",
	"previous_p95_ms",
	"delta_p95_pct",
	"is_new",
}


class TestLatencyReport(FrappeTestCase):
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
						"title": f"_Test Latency {suffix}",
						"process_id": f"_lat_{suffix}",
						"version": 1,
					}
				)
				.insert()
				.name
			)

	def setUp(self):
		frappe.set_user("Administrator")
		tag = frappe.generate_hash(length=6)
		self.model = f"lat-model-{tag}"
		self.element = f"lat_task_{tag}"

	def _run(self, day, latency=1000, status="Success", element=None, process_model=None, **extra):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": element or self.element,
				"bpmn_label": "Latency probe",
				"process_model": process_model or self.maps[0],
				"model": self.model,
				"status": status,
				"agent_latency_ms": latency,
				"started_at": f"{day} 10:00:00",
				**extra,
			}
		).insert()

	def _step(self, run, index, role, kind, latency, content="answer"):
		frappe.get_doc(
			{
				"doctype": "AI Agent Step",
				"run": run.name,
				"step_index": index,
				"role": role,
				"step_kind": kind,
				"latency_ms": latency,
				"content": content,
			}
		).insert()

	def _agent(self):
		suffix = frappe.generate_hash(length=6)
		return (
			frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": f"Latency Probe {suffix}",
					"agent_id": f"latency_probe_{suffix}",
					"agent_framework": "Direct API",
					"agent_type": "Background",
					"enabled": 1,
					"system_prompt": "You answer.",
				}
			)
			.insert()
			.name
		)

	def _report(self, from_date=FROM, to_date=TO, **kwargs):
		return get_performance_report(from_date=from_date, to_date=to_date, model=self.model, **kwargs)

	def test_only_finished_top_level_runs_count_and_empty_buckets_are_null(self):
		parent = self._run("2026-09-01", 1000)
		self._run("2026-09-02", 2000, "Error")
		self._run("2026-09-03", 9000, "Running")
		self._run("2026-09-03", 9000, "Suspended")
		self._run("2026-09-03", 9000, parent_run=parent.name)

		report = self._report()

		self.assertEqual(report["grain"], "day")
		self.assertEqual(report["summary"]["runs"], 2)
		series = report["timeseries"]
		self.assertEqual(len(series["labels"]), 7)
		self.assertEqual(series["p50_ms"][:3], [1000, 2000, None])
		self.assertEqual(series["p95_ms"][:3], [1000, 2000, None])
		self.assertEqual(series["runs"][:3], [1, 1, 0])

	def test_a_90_day_range_buckets_by_week(self):
		self._run("2026-09-01")

		report = self._report(from_date="2026-07-01", to_date="2026-09-28")

		self.assertEqual(report["grain"], "week")
		self.assertEqual(
			report["timeseries"]["labels"],
			list_bucket_labels(getdate("2026-07-01"), getdate("2026-09-28"), "week"),
		)

	def test_agent_time_is_measured_not_wall_clock(self):
		self._run("2026-09-02", 3000, duration_ms=90000, human_wait_ms=87000)

		summary = self._report()["summary"]

		self.assertEqual((summary["p50_ms"], summary["p95_ms"], summary["total_ms"]), (3000, 3000, 3000))

	def test_percentiles_use_measured_runs_only(self):
		self._run("2026-09-02", 0)
		self._run("2026-09-02", 0)
		self._run("2026-09-03", 4000)

		summary = self._report()["summary"]

		self.assertEqual((summary["runs"], summary["measured_runs"]), (3, 1))
		self.assertEqual((summary["p50_ms"], summary["p95_ms"]), (4000, 4000))

	def test_elements_split_by_process_and_sort_by_total_time(self):
		self._run("2026-09-02", 1000)
		self._run("2026-09-02", 5000, process_model=self.maps[1])
		self._run("2026-09-03", 6000, process_model=self.maps[1], status="Error")

		elements = self._report()["elements"]

		self.assertEqual(
			[e["key"] for e in elements],
			[f"{self.element}|{self.maps[1]}|{self.model}", f"{self.element}|{self.maps[0]}|{self.model}"],
		)
		self.assertEqual(set(elements[0]), ELEMENT_FIELDS)
		self.assertEqual(
			(elements[0]["runs"], elements[0]["error_runs"], elements[0]["total_ms"]), (2, 1, 11000)
		)

	def test_avg_steps_follows_the_agent_filter(self):
		mine, other = self._agent(), self._agent()
		run = self._run("2026-09-02", agent_configuration=mine)
		for index in range(2):
			self._step(run, index, "assistant", "model_call", 500)
		other_run = self._run("2026-09-02", agent_configuration=other)
		for index in range(6):
			self._step(other_run, index, "assistant", "model_call", 500)

		elements = self._report(agent_configuration=mine)["elements"]

		self.assertEqual([e["avg_steps"] for e in elements], [2.0])

	def test_the_prior_period_fills_the_deltas(self):
		self._run(PRIOR_DAY, 4000)
		self._run("2026-09-02", 6000)

		report = self._report()
		summary = report["summary"]

		self.assertEqual((report["previous_from"], report["previous_to"]), ("2026-08-25", "2026-08-31"))
		self.assertEqual((summary["previous_p50_ms"], summary["previous_p95_ms"]), (4000, 4000))
		self.assertEqual((summary["delta_p50_pct"], summary["delta_p95_pct"]), (50.0, 50.0))
		self.assertEqual((summary["previous_time_in_tools"], summary["delta_time_in_tools_pt"]), (0.0, 0.0))
		element = report["elements"][0]
		self.assertEqual(
			(element["previous_p95_ms"], element["delta_p95_pct"], element["is_new"]), (4000, 50.0, False)
		)

	def test_no_prior_runs_leaves_the_deltas_empty(self):
		self._run("2026-09-02", 6000)

		report = self._report()
		summary = report["summary"]

		for key in (
			"previous_p95_ms",
			"delta_p50_pct",
			"delta_p95_pct",
			"previous_time_in_tools",
			"delta_time_in_tools_pt",
		):
			self.assertIsNone(summary[key], key)
		self.assertTrue(report["elements"][0]["is_new"])
		self.assertIsNone(report["elements"][0]["delta_p95_pct"])

	def test_time_split_shares_step_latency_by_kind(self):
		run = self._run("2026-09-02", 9000)
		self._step(run, 0, "system", "prompt", 0)
		self._step(run, 1, "assistant", "sub_call", 5000, "[sub-call: lat_test_review via lat-model]")
		self._step(run, 2, "tool", "tool_turn", 3000)
		self._step(run, 3, "assistant", "model_call", 1000)

		summary = self._report()["summary"]

		self.assertEqual(
			(
				summary["model_share"],
				summary["tool_share"],
				summary["sub_call_share"],
				summary["time_in_tools"],
			),
			(11.1, 33.3, 55.6, 88.9),
		)

	def test_export_writes_one_row_per_element_as_csv_or_xlsx(self):
		self._run("2026-09-02", 1000)
		self._run("2026-09-02", 2000, element=f"{self.element}_other")

		export_latency_report(from_date=FROM, to_date=TO, model=self.model)

		self.assertEqual(frappe.response["filename"], f"latency-model-{FROM}-to-{TO}.csv")
		rows = list(csv.reader(io.StringIO(frappe.response["filecontent"].decode("utf-8-sig"))))
		self.assertEqual(len(rows), 3)
		self.assertEqual(len(rows[0]), len(ELEMENT_FIELDS))

		export_latency_report(from_date=FROM, to_date=TO, model=self.model, fmt="xlsx")

		self.assertEqual(frappe.response["filename"], f"latency-model-{FROM}-to-{TO}.xlsx")
		self.assertEqual(frappe.response["type"], "binary")
		with self.assertRaises(frappe.ValidationError):
			export_latency_report(from_date=FROM, to_date=TO, fmt="pdf")

	def test_the_legacy_keys_stay_for_the_current_tab(self):
		self._run("2026-09-02", 1000, duration_ms=5000)

		report = self._report()

		self.assertEqual(report["rows"][0]["p95_duration_ms"], 5000)
		self.assertEqual(len(report["trend"]["labels"]), 7)

	def test_a_user_without_system_manager_is_refused(self):
		email = f"lat-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Latency", "send_welcome_email": 0}
		).insert()
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		frappe.set_user(email)

		# frappe.only_for is a no-op while in_test is set, so the guard cannot fire unless it is cleared.
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				get_performance_report(from_date=FROM, to_date=TO)
			with self.assertRaises(frappe.PermissionError):
				export_latency_report(from_date=FROM, to_date=TO)
		finally:
			frappe.flags.in_test = True
