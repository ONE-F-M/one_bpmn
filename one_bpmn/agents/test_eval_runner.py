# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the eval runner module.

Uses unittest.mock to patch the executor so that no real LLM calls are made.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents.executor import (
	ErrorCode,
	ExecutorResult,
	TokenUsage,
)
from one_bpmn.agents.eval_runner import (
	_assert_contains,
	_assert_equals,
	_assert_llm_judge,
	_assert_regex,
	_assert_schema_valid,
	_evaluate_assertions,
	_execute_eval_suite,
	run_eval_suite,
	JUDGE_PROMPT_TEMPLATE,
)


class TestEvalRunnerAssertions(FrappeTestCase):
	"""Unit tests for individual assertion handlers."""

	# ── contains ──────────────────────────────────────────────────────

	def test_contains_pass(self):
		passed, msg = _assert_contains("The answer is 42.", "42")
		self.assertTrue(passed)
		self.assertEqual(msg, "")

	def test_contains_case_insensitive(self):
		passed, msg = _assert_contains("Hello World", "hello")
		self.assertTrue(passed)

	def test_contains_fail(self):
		passed, msg = _assert_contains("The answer is 42.", "99")
		self.assertFalse(passed)
		self.assertIn("99", msg)

	# ── regex ─────────────────────────────────────────────────────────

	def test_regex_pass(self):
		passed, msg = _assert_regex("Order #12345 confirmed.", r"#\d{5}")
		self.assertTrue(passed)

	def test_regex_fail(self):
		passed, msg = _assert_regex("No numbers here.", r"\d{5}")
		self.assertFalse(passed)

	def test_regex_invalid_pattern(self):
		passed, msg = _assert_regex("anything", r"[invalid")
		self.assertFalse(passed)
		self.assertIn("Invalid regex", msg)

	# ── equals ────────────────────────────────────────────────────────

	def test_equals_pass(self):
		passed, msg = _assert_equals("  hello  ", "hello")
		self.assertTrue(passed)

	def test_equals_fail(self):
		passed, msg = _assert_equals("hello", "world")
		self.assertFalse(passed)

	# ── schema_valid ──────────────────────────────────────────────────

	def test_schema_valid_pass(self):
		output = json.dumps({"name": "Alice", "age": 30})
		schema = json.dumps({
			"type": "object",
			"required": ["name", "age"],
			"properties": {
				"name": {"type": "string"},
				"age": {"type": "integer"},
			},
		})
		passed, msg = _assert_schema_valid(output, schema)
		self.assertTrue(passed)
		self.assertEqual(msg, "")

	def test_schema_valid_fail_invalid_json(self):
		passed, msg = _assert_schema_valid("not json", '{"type": "object"}')
		self.assertFalse(passed)
		self.assertIn("not valid JSON", msg)

	def test_schema_valid_fail_schema_mismatch(self):
		output = json.dumps({"name": 123})  # name should be string
		schema = json.dumps({
			"type": "object",
			"properties": {"name": {"type": "string"}},
		})
		passed, msg = _assert_schema_valid(output, schema)
		self.assertFalse(passed)
		self.assertIn("Schema validation failed", msg)

	def test_schema_valid_fail_bad_schema(self):
		passed, msg = _assert_schema_valid('{"name": "Alice"}', "not json")
		self.assertFalse(passed)
		self.assertIn("Schema is not valid JSON", msg)


class TestEvaluateAssertions(FrappeTestCase):
	"""Tests for the _evaluate_assertions aggregator."""

	def _make_assertion_row(self, assertion_type, value):
		"""Create a mock assertion row matching the child table interface."""
		row = MagicMock()
		row.assertion_type = assertion_type
		row.value = value
		return row

	def test_all_pass(self):
		assertions = [
			self._make_assertion_row("contains", "hello"),
			self._make_assertion_row("equals", "hello world"),
		]
		results = _evaluate_assertions(assertions, "hello world")
		self.assertTrue(all(r["passed"] for r in results))

	def test_mixed_results(self):
		assertions = [
			self._make_assertion_row("contains", "hello"),
			self._make_assertion_row("contains", "goodbye"),
		]
		results = _evaluate_assertions(assertions, "hello world")
		self.assertTrue(results[0]["passed"])
		self.assertFalse(results[1]["passed"])

	def test_unsupported_assertion_type(self):
		assertions = [self._make_assertion_row("unknown_type", "some value")]
		results = _evaluate_assertions(assertions, "output text")
		self.assertFalse(results[0]["passed"])
		self.assertIn("not handled", results[0]["message"])


class TestRunEvalSuite(FrappeTestCase):
	"""Integration tests for run_eval_suite and _execute_eval_suite."""

	def tearDown(self):
		frappe.set_user("Administrator")

	def _make_suite(self):
		"""Create a fresh, uniquely-titled suite for test isolation."""
		process_model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not process_model:
			self.skipTest("No BPMN Process Model exists for testing")

		doc = frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": f"Runner Test Suite {frappe.generate_hash(length=6)}",
			"process_model": process_model,
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_provider(self):
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

	def _make_case(self, suite_name, **kwargs):
		provider = self._make_provider()
		defaults = {
			"doctype": "AI Eval Case",
			"title": "Runner Test Case",
			"suite": suite_name,
			"provider": provider,
			"model": "gpt-4o",
			"backend": "direct_api",
			"input_user_prompt": "What is 2 + 2?",
		}
		defaults.update(kwargs)
		doc = frappe.get_doc(defaults)
		doc.insert(ignore_permissions=True)
		return doc

	# ── run_eval_suite whitelisted method ─────────────────────────────

	def test_run_eval_suite_permission_check(self):
		"""Non-System Manager should be rejected."""
		# Create a test user without System Manager role
		test_email = "eval_test_user@example.com"
		if not frappe.db.exists("User", test_email):
			user = frappe.get_doc({
				"doctype": "User",
				"email": test_email,
				"first_name": "Eval Test",
				"user_type": "Website User",
			})
			user.insert(ignore_permissions=True)

		frappe.set_user(test_email)
		# frappe.only_for() skips checks when in_test=True, so we
		# temporarily disable the flag to verify the permission guard.
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				run_eval_suite(suite_name="__any__")
		finally:
			frappe.flags.in_test = True

	def test_run_eval_suite_nonexistent_suite(self):
		"""Calling with a non-existent suite should throw DoesNotExistError."""
		with self.assertRaises(frappe.DoesNotExistError):
			run_eval_suite(suite_name="__nonexistent__")

	@patch("one_bpmn.agents.eval_runner.frappe.enqueue")
	def test_run_eval_suite_creates_run_and_enqueues(self, mock_enqueue):
		"""run_eval_suite should create an AI Eval Run and enqueue the job."""
		suite_name = self._make_suite()
		run_name = run_eval_suite(suite_name=suite_name)

		self.assertTrue(run_name)
		run = frappe.get_doc("AI Eval Run", run_name)
		self.assertEqual(run.status, "Running")
		self.assertEqual(run.suite, suite_name)
		self.assertEqual(run.backend, "live")
		self.assertTrue(run.started_at)

		mock_enqueue.assert_called_once()
		call_kwargs = mock_enqueue.call_args
		self.assertEqual(
			call_kwargs.kwargs.get("method") or call_kwargs[1].get("method"),
			"one_bpmn.agents.eval_runner._execute_eval_suite",
		)

	# ── _execute_eval_suite background job ────────────────────────────

	def _mock_executor_success(self, output_text="The answer is 4.", tokens=150):
		"""Return a mock executor class that produces a successful result."""
		mock_executor = MagicMock()
		mock_executor.return_value.run.return_value = ExecutorResult(
			output=output_text,
			token_usage=TokenUsage(prompt_tokens=50, completion_tokens=100, total_tokens=tokens),
			error_code=ErrorCode.SUCCESS,
		)
		return mock_executor

	def _mock_executor_failure(self, error_msg="API Error"):
		"""Return a mock executor class that produces an error result."""
		mock_executor = MagicMock()
		mock_executor.return_value.run.return_value = ExecutorResult(
			error_code=ErrorCode.FAILED_MODEL_CALL,
			error_message=error_msg,
		)
		return mock_executor

	@patch("one_bpmn.agents.eval_runner.frappe.publish_realtime")
	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_execute_all_cases_pass(self, mock_get_executor, mock_publish):
		"""When all assertions pass, run status should be Passed."""
		suite_name = self._make_suite()
		self._make_case(suite_name, assertions=[
			{"assertion_type": "contains", "value": "4"},
		])

		mock_get_executor.return_value = self._mock_executor_success()

		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		})
		run.insert(ignore_permissions=True)
		frappe.db.commit()

		_execute_eval_suite(run.name)

		run.reload()
		self.assertEqual(run.status, "Passed")
		self.assertGreater(run.total_cases, 0)
		self.assertEqual(run.passed_cases, run.total_cases)
		self.assertEqual(run.failed_cases, 0)
		self.assertTrue(run.ended_at)

		mock_publish.assert_any_call(
			event="eval_run_completed",
			message={"run_name": run.name},
		)

	@patch("one_bpmn.agents.eval_runner.frappe.publish_realtime")
	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_execute_case_assertion_fails(self, mock_get_executor, mock_publish):
		"""When an assertion fails, the case and run should be Failed."""
		suite_name = self._make_suite()
		self._make_case(suite_name, assertions=[
			{"assertion_type": "contains", "value": "banana"},
		])

		mock_get_executor.return_value = self._mock_executor_success(
			output_text="The answer is 4."
		)

		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		})
		run.insert(ignore_permissions=True)
		frappe.db.commit()

		_execute_eval_suite(run.name)

		run.reload()
		self.assertEqual(run.status, "Failed")
		self.assertGreater(run.failed_cases, 0)

	@patch("one_bpmn.agents.eval_runner.frappe.publish_realtime")
	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_execute_case_executor_error(self, mock_get_executor, mock_publish):
		"""When the executor returns an error, the case result should be Error."""
		suite_name = self._make_suite()
		self._make_case(suite_name)

		mock_get_executor.return_value = self._mock_executor_failure("Timeout")

		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		})
		run.insert(ignore_permissions=True)
		frappe.db.commit()

		_execute_eval_suite(run.name)

		run.reload()
		self.assertEqual(run.status, "Failed")
		error_results = [r for r in run.results if r.status == "Error"]
		self.assertGreater(len(error_results), 0)
		self.assertIn("Timeout", error_results[0].error_message)

	@patch("one_bpmn.agents.eval_runner.frappe.publish_realtime")
	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_execute_case_exception_does_not_abort_suite(self, mock_get_executor, mock_publish):
		"""An unexpected exception in one case should not abort the entire suite."""
		suite_name = self._make_suite()
		self._make_case(suite_name, title="Case that will throw")
		self._make_case(suite_name, title="Case that will pass", assertions=[
			{"assertion_type": "contains", "value": "4"},
		])

		# The executor raises an exception on first call, succeeds on second
		mock_exec = MagicMock()
		mock_exec.return_value.run.side_effect = [
			RuntimeError("Unexpected boom"),
			ExecutorResult(
				output="The answer is 4.",
				token_usage=TokenUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
				error_code=ErrorCode.SUCCESS,
			),
		]
		mock_get_executor.return_value = mock_exec

		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		})
		run.insert(ignore_permissions=True)
		frappe.db.commit()

		_execute_eval_suite(run.name)

		run.reload()
		# Both cases should have results — suite was not aborted
		self.assertEqual(run.total_cases, 2)
		self.assertEqual(len(run.results), 2)
		statuses = [r.status for r in run.results]
		self.assertIn("Error", statuses)
		self.assertIn("Passed", statuses)

	@patch("one_bpmn.agents.eval_runner.frappe.publish_realtime")
	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_execute_records_tokens(self, mock_get_executor, mock_publish):
		"""Token usage should be recorded in the result row."""
		suite_name = self._make_suite()
		self._make_case(suite_name)

		mock_get_executor.return_value = self._mock_executor_success(tokens=250)

		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		})
		run.insert(ignore_permissions=True)
		frappe.db.commit()

		_execute_eval_suite(run.name)

		run.reload()
		result_with_tokens = [r for r in run.results if r.tokens_used == 250]
		self.assertGreater(len(result_with_tokens), 0)

	@patch("one_bpmn.agents.eval_runner.frappe.publish_realtime")
	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_execute_realtime_event(self, mock_get_executor, mock_publish):
		"""Completion should publish eval_run_completed realtime event."""
		suite_name = self._make_suite()
		self._make_case(suite_name)

		mock_get_executor.return_value = self._mock_executor_success()

		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": "Running",
			"backend": "live",
			"started_at": now_datetime(),
		})
		run.insert(ignore_permissions=True)
		frappe.db.commit()

		_execute_eval_suite(run.name)

		mock_publish.assert_any_call(
			event="eval_run_completed",
			message={"run_name": run.name},
		)


class TestLlmJudgeAssertion(FrappeTestCase):
	"""Tests for the llm_judge assertion handler."""

	def _make_row(self, value="Be helpful", provider="P", model="m", threshold=4):
		row = MagicMock()
		row.assertion_type = "llm_judge"
		row.value = value
		row.judge_provider = provider
		row.judge_model = model
		row.pass_threshold = threshold
		return row

	def _mock_success(self, score=5, explanation="Good"):
		"""Return a mock executor that returns a valid judge JSON."""
		mock = MagicMock()
		mock.return_value.run.return_value = ExecutorResult(
			output={"score": score, "explanation": explanation},
			error_code=ErrorCode.SUCCESS,
		)
		return mock

	# ── Score meets threshold → pass ──────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_pass(self, mock_get):
		mock_get.return_value = self._mock_success(score=5, explanation="Great")
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row())
		self.assertTrue(result["passed"])
		self.assertEqual(result["score"], 5)
		self.assertEqual(result["explanation"], "Great")
		self.assertEqual(result["type"], "llm_judge")

	# ── Score below threshold → fail ──────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_fail_low_score(self, mock_get):
		mock_get.return_value = self._mock_success(score=2, explanation="Poor")
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row())
		self.assertFalse(result["passed"])
		self.assertEqual(result["score"], 2)

	# ── Custom threshold ──────────────────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_custom_threshold(self, mock_get):
		mock_get.return_value = self._mock_success(score=3)
		row = self._make_row(threshold=3)
		result = _assert_llm_judge("AI output", "Be helpful", row)
		self.assertTrue(result["passed"])

	# ── Default threshold when 0/None ─────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_default_threshold(self, mock_get):
		mock_get.return_value = self._mock_success(score=4)
		row = self._make_row(threshold=0)
		result = _assert_llm_judge("AI output", "Be helpful", row)
		self.assertTrue(result["passed"])  # default threshold is 4

	# ── Invalid JSON response ─────────────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_invalid_json(self, mock_get):
		mock = MagicMock()
		mock.return_value.run.return_value = ExecutorResult(
			output="not valid json",
			error_code=ErrorCode.SUCCESS,
		)
		mock_get.return_value = mock
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row())
		self.assertFalse(result["passed"])
		self.assertEqual(result["explanation"], "Judge returned invalid JSON")

	# ── Executor error ────────────────────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_executor_error(self, mock_get):
		mock = MagicMock()
		mock.return_value.run.return_value = ExecutorResult(
			error_code=ErrorCode.FAILED_MODEL_CALL,
			error_message="API timeout",
		)
		mock_get.return_value = mock
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row())
		self.assertFalse(result["passed"])
		self.assertIn("Judge call failed", result["explanation"])
		self.assertIn("API timeout", result["explanation"])

	# ── Executor raises exception ─────────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_executor_exception(self, mock_get):
		mock_get.side_effect = RuntimeError("Boom")
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row())
		self.assertFalse(result["passed"])
		self.assertIn("Judge call failed", result["explanation"])

	# ── Judge returns dict directly (response_format=json) ────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_dict_output(self, mock_get):
		mock_get.return_value = self._mock_success(score=4, explanation="OK")
		result = _assert_llm_judge("AI output", "rubric", self._make_row())
		self.assertTrue(result["passed"])
		self.assertEqual(result["score"], 4)

	# ── Judge returns JSON string ─────────────────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_string_json_output(self, mock_get):
		mock = MagicMock()
		mock.return_value.run.return_value = ExecutorResult(
			output='{"score": 5, "explanation": "Perfect"}',
			error_code=ErrorCode.SUCCESS,
		)
		mock_get.return_value = mock
		result = _assert_llm_judge("AI output", "rubric", self._make_row())
		self.assertTrue(result["passed"])
		self.assertEqual(result["score"], 5)

	# ── Prompt template format ────────────────────────────────────────

	def test_judge_prompt_template_format(self):
		prompt = JUDGE_PROMPT_TEMPLATE.format(
			rubric="Be professional",
			actual_output="Hello there",
		)
		self.assertIn("Be professional", prompt)
		self.assertIn("Hello there", prompt)
		self.assertIn("Score the response from 1 to 5", prompt)

	# ── Integration: llm_judge via _evaluate_assertions ───────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_evaluate_assertions_with_llm_judge(self, mock_get):
		mock_get.return_value = self._mock_success(score=5)
		row = self._make_row()
		results = _evaluate_assertions([row], "AI output")
		self.assertEqual(len(results), 1)
		self.assertTrue(results[0]["passed"])
		self.assertEqual(results[0]["type"], "llm_judge")
		self.assertEqual(results[0]["score"], 5)

