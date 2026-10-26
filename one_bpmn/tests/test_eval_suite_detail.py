# Copyright (c) 2026, one-fm and contributors

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import make_eval_run, make_eval_suite
from one_bpmn.api.eval_api import get_suite_detail

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]


class TestEvalSuiteDetail(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite()
		self.runs = []
		for i in range(30):
			run = make_eval_run(self.suite.name, status="Passed", total_cases=1, passed_cases=1)
			# Distinct creation times, oldest first, so the newest-first order is fixed.
			frappe.db.set_value("AI Eval Run", run.name, "creation", add_to_date(now_datetime(), minutes=i - 60))
			self.runs.append(run.name)

	def test_runs_come_one_page_at_a_time_with_the_total(self):
		first = get_suite_detail(self.suite.name, start=0, page_length=25)
		second = get_suite_detail(self.suite.name, start=25, page_length=25)
		self.assertEqual(first["total_runs"], 30)
		self.assertEqual([r["name"] for r in first["runs"]], self.runs[::-1][:25])
		self.assertEqual([r["name"] for r in second["runs"]], self.runs[::-1][25:])
		self.assertEqual(second["start"], 25)

	def test_run_numbers_count_from_the_oldest_on_every_page(self):
		second = get_suite_detail(self.suite.name, start=25, page_length=25)
		self.assertIn("Run 5 ", second["runs"][0]["display_title"])

	def test_the_dashboard_reads_the_latest_runs_whatever_the_page(self):
		frappe.db.set_value("AI Eval Run", self.runs[-1], "status", "Failed")
		later_page = get_suite_detail(self.suite.name, start=25, page_length=25)
		self.assertEqual(later_page["metrics"]["latest"]["status"], "Failed")

	def test_the_page_size_is_capped(self):
		self.assertEqual(len(get_suite_detail(self.suite.name, page_length=1000)["runs"]), 30)
		self.assertEqual(len(get_suite_detail(self.suite.name, page_length=0)["runs"]), 1)
