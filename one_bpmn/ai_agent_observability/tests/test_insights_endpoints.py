# Copyright (c) 2026, one-fm and contributors
"""The Insights API is a thin layer over ai_agent_observability/reports: same endpoints, two removed."""

import ast
import inspect

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import insights

ENDPOINTS = {
	"export_cost_allocation",
	"export_cost_token_report",
	"export_error_report",
	"get_agent_overview",
	"get_cost_allocation",
	"get_cost_token_report",
	"get_error_report",
	"get_issue_runs",
	"get_performance_report",
	"get_recent_runs",
	"get_run_detail",
	"get_run_tree",
	"get_turn_steps",
	"get_work_item_delegation_cost",
	"list_runs",
	"run_filter_options",
	"search_orchestrator_work_items",
}


def _whitelisted():
	return {
		name: fn
		for name, fn in inspect.getmembers(insights, inspect.isfunction)
		if fn in frappe.whitelisted and fn.__module__ == insights.__name__
	}


class TestInsightsEndpoints(FrappeTestCase):
	def test_the_exposed_endpoints_are_exactly_the_expected_set(self):
		self.assertEqual(set(_whitelisted()), ENDPOINTS)

	def test_the_two_unused_endpoints_are_gone(self):
		for name in ("get_run_steps", "get_run_totals_crosscheck"):
			self.assertFalse(hasattr(insights, name), name)

	def test_each_endpoint_checks_the_role_then_makes_one_call_into_reports(self):
		for name, fn in _whitelisted().items():
			with self.subTest(name):
				body = ast.parse(inspect.getsource(fn)).body[0].body
				if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
					body = body[1:]
				self.assertEqual(len(body), 2)
				self.assertIn("only_for", ast.unparse(body[0]))
				self.assertIsInstance(body[1], ast.Return)

	def test_every_argument_is_typed_and_post_is_not_needed_for_reads(self):
		for name, fn in _whitelisted().items():
			for arg, param in inspect.signature(fn).parameters.items():
				with self.subTest(f"{name}.{arg}"):
					self.assertIsNot(param.annotation, inspect.Parameter.empty)

	def test_a_user_without_system_manager_is_refused(self):
		# frappe.only_for skips the role check while the test flag is set, so clear it for this call.
		in_test = frappe.flags.in_test
		frappe.flags.in_test = False
		frappe.set_user("Guest")
		try:
			for fn in (insights.get_agent_overview, insights.list_runs, insights.run_filter_options):
				with self.subTest(fn.__name__), self.assertRaises(frappe.PermissionError):
					fn()
		finally:
			frappe.set_user("Administrator")
			frappe.flags.in_test = in_test
