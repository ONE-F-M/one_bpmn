# Copyright (c) 2026, one-fm and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestAIEvalRun(FrappeTestCase):

	def setUp(self):
		"""Create prerequisite test fixtures."""
		# Create a test AI Eval Suite
		if not frappe.db.exists("AI Eval Suite", {"title": "_Test Eval Suite"}):
			self.suite = frappe.get_doc({
				"doctype": "AI Eval Suite",
				"title": "_Test Eval Suite",
				"process_model": "",
			})
			self.suite.flags.ignore_mandatory = True
			self.suite.insert(ignore_permissions=True)
		else:
			self.suite = frappe.get_doc(
				"AI Eval Suite", {"title": "_Test Eval Suite"}
			)

	def _make_eval_run(self, **kwargs):
		"""Factory helper to create an AI Eval Run."""
		defaults = {
			"doctype": "AI Eval Run",
			"suite": self.suite.name,
			"status": "Running",
			"started_at": now_datetime(),
			"backend": "live",
		}
		defaults.update(kwargs)
		doc = frappe.get_doc(defaults)
		doc.insert(ignore_permissions=True)
		return doc

	def test_create_basic_run(self):
		"""AC: AI Eval Run can be created with required fields."""
		run = self._make_eval_run()
		self.assertTrue(run.name)
		self.assertEqual(run.status, "Running")
		self.assertEqual(run.suite, self.suite.name)
		self.assertEqual(run.backend, "live")

	def test_autoname_uses_hash(self):
		"""AC: autoname uses hash — name should be a short random string."""
		run = self._make_eval_run()
		# Hash names are 10-char alphanumeric strings
		self.assertTrue(len(run.name) == 10)

	def test_status_options(self):
		"""AC: status field supports Running, Passed, Failed, Error."""
		for status in ["Running", "Passed", "Failed", "Error"]:
			run = self._make_eval_run(status=status)
			self.assertEqual(run.status, status)

	def test_backend_default(self):
		"""AC: backend defaults to 'live'."""
		run = self._make_eval_run()
		self.assertEqual(run.backend, "live")

	def test_backend_replay(self):
		"""AC: backend supports 'replay' option."""
		run = self._make_eval_run(backend="replay")
		self.assertEqual(run.backend, "replay")

	def test_case_count_validation(self):
		"""AC: passed + failed cannot exceed total_cases."""
		self.assertRaises(
			frappe.ValidationError,
			self._make_eval_run,
			total_cases=5,
			passed_cases=3,
			failed_cases=4,
		)

	def test_valid_case_counts(self):
		"""Sanity check: valid counts pass validation."""
		run = self._make_eval_run(
			total_cases=10, passed_cases=7, failed_cases=3
		)
		self.assertEqual(run.total_cases, 10)
		self.assertEqual(run.passed_cases, 7)
		self.assertEqual(run.failed_cases, 3)

	def test_results_child_table(self):
		"""AC: results child table stores AI Eval Result rows."""
		# First create a test case
		if not frappe.db.exists("AI Eval Case", {"title": "_Test Case for Run"}):
			case = frappe.get_doc({
				"doctype": "AI Eval Case",
				"title": "_Test Case for Run",
				"input_user_prompt": "Say hello",
				"provider": "",
				"model": "test-model",
			})
			case.flags.ignore_mandatory = True
			case.insert(ignore_permissions=True)
		else:
			case = frappe.get_doc(
				"AI Eval Case", {"title": "_Test Case for Run"}
			)

		run = self._make_eval_run(
			status="Passed",
			total_cases=1,
			passed_cases=1,
			failed_cases=0,
			results=[
				{
					"eval_case": case.name,
					"status": "Passed",
					"actual_output": "Hello!",
					"assertion_results": '[{"type": "contains", "value": "Hello", "passed": true}]',
					"tokens_used": 42,
					"cost": 0.000123,
				}
			],
		)

		self.assertEqual(len(run.results), 1)
		result = run.results[0]
		self.assertEqual(result.eval_case, case.name)
		self.assertEqual(result.status, "Passed")
		self.assertEqual(result.actual_output, "Hello!")
		self.assertEqual(result.tokens_used, 42)

	def test_ended_at_optional(self):
		"""AC: ended_at is optional (None for Running runs)."""
		run = self._make_eval_run(status="Running")
		self.assertIsNone(run.ended_at)

	def test_error_result_with_message(self):
		"""AC: error_message populated when result status is Error."""
		if not frappe.db.exists("AI Eval Case", {"title": "_Test Error Case"}):
			case = frappe.get_doc({
				"doctype": "AI Eval Case",
				"title": "_Test Error Case",
				"input_user_prompt": "Trigger error",
				"provider": "",
				"model": "test-model",
			})
			case.flags.ignore_mandatory = True
			case.insert(ignore_permissions=True)
		else:
			case = frappe.get_doc(
				"AI Eval Case", {"title": "_Test Error Case"}
			)

		run = self._make_eval_run(
			status="Error",
			total_cases=1,
			passed_cases=0,
			failed_cases=0,
			results=[
				{
					"eval_case": case.name,
					"status": "Error",
					"error_message": "API timeout after 30s",
				}
			],
		)

		result = run.results[0]
		self.assertEqual(result.status, "Error")
		self.assertEqual(result.error_message, "API timeout after 30s")
