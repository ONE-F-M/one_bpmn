# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestAIEvalRun(FrappeTestCase):
	"""Tests for AI Eval Run DocType."""

	def tearDown(self):
		frappe.set_user("Administrator")

	def _get_or_create_suite(self):
		"""Return a test AI Eval Suite name, creating one if needed."""
		name = frappe.db.get_value("AI Eval Suite", {}, "name")
		if name:
			return name

		process_model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not process_model:
			self.skipTest("No BPMN Process Model exists for testing")

		doc = frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": "Test Suite for Runs",
			"process_model": process_model,
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_provider(self):
		"""Create a test AI Provider if it doesn't exist."""
		if not frappe.db.exists("AI Provider", "Test Provider"):
			frappe.get_doc({
				"doctype": "AI Provider",
				"provider_name": "Test Provider",
				"provider_type": "OpenAI",
				"api_endpoint": "https://api.openai.com/v1",
				"api_key": "sk-test-key",
				"default_model": "gpt-4o",
				"enabled": 1,
			}).insert(ignore_permissions=True)
		return "Test Provider"

	def _make_eval_case(self, suite_name):
		"""Create a test AI Eval Case linked to the given suite."""
		provider = self._make_provider()
		doc = frappe.get_doc({
			"doctype": "AI Eval Case",
			"title": "Run Test Case",
			"suite": suite_name,
			"provider": provider,
			"model": "gpt-4o",
			"input_user_prompt": "What is 2 + 2?",
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_eval_run(self, **kwargs):
		"""Factory function for creating test AI Eval Run documents."""
		suite = kwargs.pop("suite", None) or self._get_or_create_suite()
		defaults = {
			"doctype": "AI Eval Run",
			"suite": suite,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		}
		defaults.update(kwargs)
		doc = frappe.get_doc(defaults)
		doc.insert(ignore_permissions=True)
		return doc

	def test_basic_create_and_hash_autoname(self):
		"""AI Eval Run should be created with a random hash name."""
		doc = self._make_eval_run()
		self.assertTrue(doc.name)
		self.assertEqual(len(doc.name), 10)  # Frappe hash names are 10 chars
		self.assertEqual(doc.status, "Running")

	def test_default_backend(self):
		"""Backend should default to 'live'."""
		doc = self._make_eval_run()
		self.assertEqual(doc.backend, "live")

	def test_suite_invalid_link(self):
		"""Creating a run with a non-existent suite should raise."""
		with self.assertRaises(frappe.exceptions.LinkValidationError):
			self._make_eval_run(suite="__nonexistent__")

	def test_status_values(self):
		"""Status should accept all valid options."""
		for status in ("Running", "Passed", "Failed", "Error"):
			doc = self._make_eval_run(status=status)
			self.assertEqual(doc.status, status)

	def test_started_at_required(self):
		"""Creating a run without started_at should raise."""
		with self.assertRaises(frappe.exceptions.MandatoryError):
			self._make_eval_run(started_at=None)

	def test_ended_at_optional(self):
		"""ended_at should accept None."""
		doc = self._make_eval_run(ended_at=None)
		self.assertFalse(doc.ended_at)

	def test_create_with_results(self):
		"""Run with per-case results in the child table should save."""
		suite = self._get_or_create_suite()
		case_name = self._make_eval_case(suite)

		doc = self._make_eval_run(
			suite=suite,
			status="Passed",
			total_cases=1,
			passed_cases=1,
			failed_cases=0,
			results=[{
				"eval_case": case_name,
				"status": "Passed",
				"actual_output": "The answer is 4.",
				"assertion_results": '[{"type": "contains", "value": "4", "passed": true}]',
				"tokens_used": 150,
				"cost": 0.000300,
			}],
		)
		self.assertEqual(len(doc.results), 1)
		self.assertEqual(doc.results[0].status, "Passed")
		self.assertEqual(doc.results[0].eval_case, case_name)

	def test_create_with_error_result(self):
		"""Run with an Error-status result should save with error_message."""
		suite = self._get_or_create_suite()
		case_name = self._make_eval_case(suite)

		doc = self._make_eval_run(
			suite=suite,
			status="Error",
			total_cases=1,
			passed_cases=0,
			failed_cases=0,
			results=[{
				"eval_case": case_name,
				"status": "Error",
				"error_message": "API timeout after 30s",
			}],
		)
		self.assertEqual(doc.results[0].status, "Error")
		self.assertEqual(doc.results[0].error_message, "API timeout after 30s")

	def test_case_count_validation(self):
		"""passed + failed exceeding total should raise."""
		with self.assertRaises(frappe.ValidationError):
			self._make_eval_run(
				total_cases=5,
				passed_cases=3,
				failed_cases=4,
			)

	def test_aggregate_counts_consistent(self):
		"""passed + failed within total_cases should save."""
		doc = self._make_eval_run(
			total_cases=10,
			passed_cases=7,
			failed_cases=3,
		)
		self.assertEqual(doc.total_cases, 10)
		self.assertEqual(doc.passed_cases, 7)
		self.assertEqual(doc.failed_cases, 3)

	def test_status_transitions(self):
		"""Run status can be updated from Running to Passed."""
		doc = self._make_eval_run(status="Running")
		doc.status = "Passed"
		doc.save(ignore_permissions=True)
		doc.reload()
		self.assertEqual(doc.status, "Passed")

	def test_multiple_results(self):
		"""Run with multiple per-case results should save all rows."""
		suite = self._get_or_create_suite()
		case1 = self._make_eval_case(suite)
		case2 = self._make_eval_case(suite)

		doc = self._make_eval_run(
			suite=suite,
			status="Failed",
			total_cases=2,
			passed_cases=1,
			failed_cases=1,
			results=[
				{
					"eval_case": case1,
					"status": "Passed",
					"actual_output": "Correct answer",
					"tokens_used": 100,
				},
				{
					"eval_case": case2,
					"status": "Failed",
					"actual_output": "Wrong answer",
					"assertion_results": '[{"type": "contains", "value": "expected", "passed": false}]',
					"tokens_used": 120,
				},
			],
		)
		self.assertEqual(len(doc.results), 2)
		statuses = [r.status for r in doc.results]
		self.assertIn("Passed", statuses)
		self.assertIn("Failed", statuses)
