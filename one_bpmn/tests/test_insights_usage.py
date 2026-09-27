# Copyright (c) 2026, one-fm and contributors
"""Date-range filtering, previous-period comparison, and CSV/XLSX export
for the AI Insights usage endpoints (get_agent_overview, get_cost_token_report,
export_cost_token_report).

Every AI Agent Run fixture uses a model name unique to its test so the sums
being asserted cannot be skewed by rows other tests (or other suites) leave
behind.

	bench run-tests --skip-before-tests --module one_bpmn.tests.test_insights_usage
"""

from __future__ import annotations

import csv
import io

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate

from one_bpmn.api.insights_api import (
	_grain_for,
	export_cost_token_report,
	get_agent_overview,
	get_cost_token_report,
	get_performance_report,
	search_orchestrator_work_items,
)

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]


class TestInsightsUsage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"usage-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)
		cls.instance = instance.name

	def _make_run(self, model, started_at, cost=0.0, tokens=0, status="Success", **extra):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": self.instance,
				"bpmn_id": "usage_probe",
				"status": status,
				"model": model,
				"started_at": started_at,
				"estimated_cost": cost,
				"total_tokens": tokens,
				**extra,
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: (
				frappe.db.exists("AI Agent Run", n)
				and frappe.delete_doc("AI Agent Run", n, force=True, ignore_permissions=True)
			)
		)
		return doc

	# -- previous-period comparison ---------------------------------------

	def test_previous_period_cost_and_bounds(self):
		model = f"usage-prev-{frappe.generate_hash(length=6)}"
		self._make_run(model, "2026-09-10 08:00:00", cost=1.0)
		self._make_run(model, "2026-09-10 09:00:00", cost=2.0)
		self._make_run(model, "2026-09-10 10:00:00", cost=3.0)
		self._make_run(model, "2026-08-30 08:00:00", cost=6.0)

		overview = get_agent_overview(from_date="2026-09-01", to_date="2026-09-30", model=model)

		self.assertEqual(overview["current"]["cost"], 6.0)
		self.assertEqual(overview["previous"]["cost"], 6.0)
		self.assertEqual(overview["delta"]["cost"], 0.0)
		self.assertEqual(overview["previous_from"], "2026-08-02")
		self.assertEqual(overview["previous_to"], "2026-08-31")

	def test_empty_previous_period_gives_null_deltas(self):
		model = f"usage-noprev-{frappe.generate_hash(length=6)}"
		self._make_run(model, "2026-09-05 08:00:00", cost=4.0, tokens=40)

		overview = get_agent_overview(from_date="2026-09-01", to_date="2026-09-30", model=model)

		self.assertEqual(overview["previous"]["runs"], 0)
		for key, value in overview["delta"].items():
			self.assertIsNone(value, f"delta.{key} should be null when the previous period is empty")

	def test_avg_cost_and_rate_deltas_in_points(self):
		model = f"usage-rates-{frappe.generate_hash(length=6)}"
		self._make_run(
			model, "2026-08-20 08:00:00", cost=1.0, total_prompt_tokens=100, total_cache_read_tokens=20
		)
		self._make_run(model, "2026-08-20 09:00:00", cost=1.0, status="Error", total_prompt_tokens=100)
		self._make_run(
			model, "2026-09-10 08:00:00", cost=3.0, total_prompt_tokens=100, total_cache_read_tokens=50
		)
		self._make_run(
			model, "2026-09-11 08:00:00", cost=1.0, total_prompt_tokens=100, total_cache_read_tokens=30
		)

		overview = get_agent_overview(from_date="2026-09-01", to_date="2026-09-30", model=model)

		self.assertEqual(overview["current"]["avg_cost"], 2.0)
		self.assertEqual(overview["delta"]["avg_cost"], 100.0)
		self.assertEqual(overview["delta"]["success_rate"], 50.0)
		self.assertEqual(overview["delta"]["cache_hit_rate"], 30.0)

		sparklines = overview["sparklines"]
		day = sparklines["labels"].index("2026-09-10")
		self.assertEqual(sparklines["avg_cost"][day], 3.0)
		self.assertEqual(sparklines["success_rate"][day], 100.0)
		self.assertEqual(sparklines["cache_hit_rate"][day], 50.0)
		empty_day = sparklines["labels"].index("2026-09-12")
		self.assertEqual(sparklines["success_rate"][empty_day], 0.0)

	# -- grain selection and bucket labels ---------------------------------

	def test_grain_day_week_month_and_empty_buckets(self):
		model = f"usage-grain-{frappe.generate_hash(length=6)}"

		day_overview = get_agent_overview(from_date="2026-01-05", to_date="2026-01-11", model=model)
		self.assertEqual(day_overview["grain"], "day")
		self.assertEqual(day_overview["sparklines"]["cost"], [0] * len(day_overview["sparklines"]["labels"]))

		week_overview = get_agent_overview(from_date="2026-01-01", to_date="2026-03-01", model=model)
		self.assertEqual(week_overview["grain"], "week")
		for label in week_overview["sparklines"]["labels"]:
			self.assertEqual(getdate(label).weekday(), 0, "week bucket label must be a Monday")
		self.assertTrue(all(v == 0 for v in week_overview["sparklines"]["cost"]))

		month_overview = get_agent_overview(from_date="2026-01-01", to_date="2026-07-25", model=model)
		self.assertEqual(month_overview["grain"], "month")
		for label in month_overview["sparklines"]["labels"]:
			self.assertEqual(getdate(label).day, 1, "month bucket label must be the 1st")
		self.assertTrue(all(v == 0 for v in month_overview["sparklines"]["tokens"]))

	def test_grain_cut_offs_are_31_and_120_days(self):
		start = getdate("2026-01-01")
		for days, grain in ((31, "day"), (32, "week"), (100, "week"), (120, "week"), (121, "month")):
			with self.subTest(days=days):
				self.assertEqual(_grain_for(start, add_days(start, days - 1)), grain)

	# -- filter_options -----------------------------------------------------

	def test_filter_options_lists_all_models_even_when_narrowed(self):
		model_a = f"usage-modA-{frappe.generate_hash(length=6)}"
		model_b = f"usage-modB-{frappe.generate_hash(length=6)}"
		now = frappe.utils.now_datetime()
		self._make_run(model_a, now, cost=1.0, tokens=10)
		self._make_run(model_b, now, cost=1.0, tokens=10)

		report = get_cost_token_report(model=model_a)

		self.assertIn(model_a, report["filter_options"]["models"])
		self.assertIn(model_b, report["filter_options"]["models"])

	def test_series_share_delta_and_totals(self):
		provider = f"usage-share-{frappe.generate_hash(length=6)}"
		frappe.get_doc({"doctype": "AI Provider", "provider": provider}).insert(ignore_permissions=True)
		model_a = f"usage-shA-{frappe.generate_hash(length=6)}"
		model_b = f"usage-shB-{frappe.generate_hash(length=6)}"
		tokens = {"provider": provider, "total_prompt_tokens": 100}
		self._make_run(model_a, "2026-09-10 08:00:00", cost=2.0, total_cache_read_tokens=40, **tokens)
		self._make_run(model_a, "2026-09-11 08:00:00", cost=1.0, total_cache_read_tokens=40, **tokens)
		self._make_run(model_b, "2026-09-12 08:00:00", cost=1.0, **tokens)
		self._make_run(model_a, "2026-08-20 08:00:00", cost=1.5, **tokens)

		report = get_cost_token_report(from_date="2026-09-01", to_date="2026-09-30", provider=provider)

		by_name = {row["name"]: row for row in report["series"]}
		self.assertEqual(by_name[model_a]["share"], 75.0)
		self.assertEqual(by_name[model_a]["avg_cost"], 1.5)
		self.assertEqual(by_name[model_a]["cache_hit_rate"], 40.0)
		self.assertEqual(by_name[model_a]["previous_cost"], 1.5)
		self.assertEqual(by_name[model_a]["delta"], 100.0)
		self.assertEqual(by_name[model_b]["share"], 25.0)
		self.assertIsNone(by_name[model_b]["delta"])
		self.assertEqual(report["total"]["avg_cost"], 1.333333)
		self.assertEqual(report["total"]["cache_hit_rate"], 26.7)

	def test_unattributed_agent_series_has_no_provider(self):
		model = f"usage-unattr-{frappe.generate_hash(length=6)}"
		for provider in ("usage-prov-a", "usage-prov-b"):
			if not frappe.db.exists("AI Provider", provider):
				frappe.get_doc({"doctype": "AI Provider", "provider": provider}).insert(
					ignore_permissions=True
				)
			self._make_run(model, "2026-09-10 08:00:00", cost=1.0, tokens=10, provider=provider)

		report = get_cost_token_report(
			from_date="2026-09-01", to_date="2026-09-30", model=model, group_by="agent"
		)

		unattributed = [row for row in report["series"] if row["name"] == "Unattributed"]
		self.assertEqual(len(unattributed), 1)
		self.assertIsNone(unattributed[0]["provider"])
		self.assertEqual(unattributed[0]["runs"], 2)

		single = get_cost_token_report(
			from_date="2026-09-01",
			to_date="2026-09-30",
			model=model,
			provider="usage-prov-a",
			group_by="agent",
		)
		self.assertEqual(
			[(row["name"], row["provider"]) for row in single["series"]], [("Unattributed", None)]
		)

	# -- token math ----------------------------------------------------------

	def test_input_output_cached_tokens_sum(self):
		model = f"usage-tok-{frappe.generate_hash(length=6)}"
		self._make_run(
			model,
			"2026-09-15 08:00:00",
			cost=1.0,
			tokens=150,  # prompt(100) + completion(50)
			total_prompt_tokens=100,
			total_completion_tokens=50,
			total_cache_read_tokens=20,
			total_cache_write_tokens=10,
		)

		overview = get_agent_overview(from_date="2026-09-01", to_date="2026-09-30", model=model)
		current = overview["current"]

		self.assertEqual(
			current["input_tokens"] + current["output_tokens"] + current["cached_tokens"],
			current["tokens"] - 10,
		)

	def test_cache_hit_rate_zero_when_no_prompt_tokens(self):
		model = f"usage-nohit-{frappe.generate_hash(length=6)}"
		self._make_run(
			model,
			"2026-09-16 08:00:00",
			cost=1.0,
			tokens=0,
			total_prompt_tokens=0,
			total_completion_tokens=0,
			total_cache_read_tokens=0,
		)

		overview = get_agent_overview(from_date="2026-09-01", to_date="2026-09-30", model=model)
		self.assertEqual(overview["current"]["cache_hit_rate"], 0.0)

	# -- permissions ----------------------------------------------------------

	def test_non_system_manager_gets_permission_error(self):
		username = f"usage-user-{frappe.generate_hash(length=6)}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": username,
				"first_name": "Usage",
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("User", username, force=True, ignore_permissions=True))

		frappe.set_user(username)
		# frappe.only_for is a no-op while in_test is set.
		frappe.flags.in_test = False
		try:
			self.assertRaises(frappe.PermissionError, get_agent_overview)
			self.assertRaises(frappe.PermissionError, get_cost_token_report)
			self.assertRaises(frappe.PermissionError, export_cost_token_report)
			self.assertRaises(frappe.PermissionError, search_orchestrator_work_items)
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")

	def test_work_item_search_lists_only_orchestrator_items(self):
		names = [w["name"] for w in search_orchestrator_work_items()]
		others = frappe.get_all("Work Item", filters={"orchestrator": 0, "name": ["in", names]}, pluck="name") if names else []
		self.assertEqual(others, [])
		self.assertLessEqual(len(names), 20)

	# -- export -----------------------------------------------------------

	def test_csv_export_shape_and_bom(self):
		model = f"usage-csv-{frappe.generate_hash(length=6)}"
		self._make_run(model, "2026-09-10 08:00:00", cost=1.0, tokens=10)
		self._make_run(model, "2026-09-11 08:00:00", cost=2.0, tokens=20)

		export_cost_token_report(from_date="2026-09-01", to_date="2026-09-30", model=model, fmt="csv")

		self.assertEqual(frappe.response["type"], "binary")
		expected_filename = "usage-model-2026-09-01-to-2026-09-30.csv"
		self.assertEqual(frappe.response["filename"], expected_filename)
		content = frappe.response["filecontent"]
		self.assertTrue(content.startswith(b"\xef\xbb\xbf"), "CSV must start with the UTF-8 BOM")

		text = content.decode("utf-8-sig")
		lines = list(csv.reader(io.StringIO(text)))
		self.assertEqual(len(lines), 3, "a header plus one row per day")

	def test_xlsx_export_returns_a_file(self):
		model = f"usage-xlsx-{frappe.generate_hash(length=6)}"
		self._make_run(model, "2026-09-10 08:00:00", cost=1.0, tokens=10)

		export_cost_token_report(from_date="2026-09-01", to_date="2026-09-30", model=model, fmt="xlsx")

		self.assertEqual(frappe.response["type"], "binary")
		self.assertEqual(frappe.response["filename"], "usage-model-2026-09-01-to-2026-09-30.xlsx")
		content = frappe.response["filecontent"]
		self.assertTrue(content[:2] == b"PK", "xlsx files are zip archives, starting with PK")

	# -- legacy keys --------------------------------------------------------

	def test_legacy_keys_are_gone(self):
		model = f"usage-legacy-{frappe.generate_hash(length=6)}"
		self._make_run(model, "2026-09-10 08:00:00", cost=1.5, tokens=30)
		self._make_run(model, "2026-09-11 08:00:00", cost=2.5, tokens=70)
		filters = {"from_date": "2026-09-01", "to_date": "2026-09-30", "model": model}

		overview = get_agent_overview(**filters)
		for key in ("runs_today", "active_errors", "avg_latency_ms", "success_rate", "total_cost", "total_tokens"):
			self.assertNotIn(key, overview)
		self.assertEqual(overview["current"]["cost"], 4.0)

		report = get_cost_token_report(**filters)
		self.assertNotIn("rows", report)
		self.assertNotIn("summary", report)
		self.assertEqual(len(report["chart_data"]["labels"]), 30)
		datasets = report["chart_data"]["datasets"]
		self.assertEqual([d["label"] for d in datasets], [model])
		self.assertNotIn("model", datasets[0])
		self.assertEqual(sum(datasets[0]["values"]), 4.0)

	def test_performance_report_filters_by_provider(self):
		model = f"usage-perf-{frappe.generate_hash(length=6)}"
		for provider in ("usage-perf-a", "usage-perf-b"):
			if not frappe.db.exists("AI Provider", provider):
				frappe.get_doc({"doctype": "AI Provider", "provider": provider}).insert(ignore_permissions=True)
		self._make_run(model, "2026-09-10 08:00:00", provider="usage-perf-a", duration_ms=1000)
		self._make_run(model, "2026-09-10 09:00:00", provider="usage-perf-b", duration_ms=3000)

		report = get_performance_report(
			from_date="2026-09-01", to_date="2026-09-30", model=model, provider="usage-perf-a"
		)

		self.assertEqual(sum(row["runs"] for row in report["rows"]), 1)

	def test_days_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			get_agent_overview(days=7)
