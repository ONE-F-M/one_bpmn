# Copyright (c) 2026, one-fm and contributors
# WI-001362 (5-02): assertion evaluators for all five assertion types.
# Gap closure against the evaluators already merged on staging: judge/
# assertion failures must surface as ERROR (never silently Passed/Failed),
# and llm_judge's own token spend must reach the Result's totals.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import eval_runner
from one_bpmn.agents.eval_runner import _evaluate_assertion

test_ignore = ["AI Eval Suite", "AI Eval Case"]


def _assertion(assertion_type, value, **extra):
	return SimpleNamespace(
		assertion_type=assertion_type,
		value=value,
		judge_provider=extra.get("judge_provider", ""),
		judge_model=extra.get("judge_model", ""),
		pass_threshold=extra.get("pass_threshold", 4),
	)


class TestAssertionEvaluators(FrappeTestCase):
	# ── Scenario 2: contains / regex / equals ──

	def test_contains(self):
		self.assertTrue(_evaluate_assertion(_assertion("contains", "world"), "Hello World")["passed"])
		self.assertFalse(_evaluate_assertion(_assertion("contains", "mars"), "Hello World")["passed"])

	def test_regex(self):
		self.assertTrue(_evaluate_assertion(_assertion("regex", r"\d{3}"), "code 123")["passed"])
		self.assertFalse(_evaluate_assertion(_assertion("regex", r"^\d+$"), "abc")["passed"])

	def test_equals(self):
		self.assertTrue(_evaluate_assertion(_assertion("equals", "yes"), " yes ")["passed"])
		self.assertFalse(_evaluate_assertion(_assertion("equals", "yes"), "no")["passed"])

	# ── Scenario 1: schema_valid ──

	def test_schema_valid(self):
		schema = '{"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}'
		self.assertTrue(_evaluate_assertion(_assertion("schema_valid", schema), '{"a": 1}')["passed"])
		bad = _evaluate_assertion(_assertion("schema_valid", schema), '{"a": "not int"}')
		self.assertFalse(bad["passed"])
		self.assertTrue(bad.get("message"))

	# ── Scenario 5: bad assertion → Error result, suite keeps going ──

	def test_invalid_regex_is_error_not_failed(self):
		result = _evaluate_assertion(_assertion("regex", "([unclosed"), "text")
		self.assertFalse(result["passed"])
		self.assertTrue(result.get("error"))

	def test_unsupported_type_is_error(self):
		result = _evaluate_assertion(_assertion("telepathy", "x"), "text")
		self.assertTrue(result.get("error"))

	# ── Scenarios 3/4: llm_judge scoring, failure = Error, cost counted ──

	def _judge_executor(self, output=None, error=False):
		from one_bpmn.agents.executor import (
			ErrorCode,
			ExecutorResult,
			TokenUsage,
		)

		class FakeJudge:
			def run(self, config, context):
				if error:
					return ExecutorResult(
						error_code=ErrorCode.FAILED_MODEL_CALL, error_message="judge down"
					)
				return ExecutorResult(
					output=output,
					token_usage=TokenUsage(prompt_tokens=40, completion_tokens=8, total_tokens=48),
				)

		return patch.object(eval_runner, "get_executor", return_value=FakeJudge)

	def test_llm_judge_passes_at_threshold(self):
		with self._judge_executor(output='{"score": 5, "explanation": "great"}'):
			result = _evaluate_assertion(_assertion("llm_judge", "Is it polite?"), "output")
		self.assertTrue(result["passed"])
		self.assertEqual(result["score"], 5)
		self.assertEqual(result["judge_prompt_tokens"], 40)
		self.assertEqual(result["judge_completion_tokens"], 8)

	def test_llm_judge_fails_below_threshold(self):
		with self._judge_executor(output='{"score": 2, "explanation": "rude"}'):
			result = _evaluate_assertion(_assertion("llm_judge", "Is it polite?"), "output")
		self.assertFalse(result["passed"])
		self.assertFalse(result.get("error", False))

	def test_llm_judge_call_failure_is_error(self):
		with self._judge_executor(error=True):
			result = _evaluate_assertion(_assertion("llm_judge", "rubric"), "output")
		self.assertTrue(result.get("error"))
		self.assertFalse(result["passed"])

	def test_llm_judge_unparseable_score_is_error(self):
		with self._judge_executor(output="not json at all {{{"):
			result = _evaluate_assertion(_assertion("llm_judge", "rubric"), "output")
		self.assertTrue(result.get("error"))

	# ── Case-level: Error status propagation + judge cost in totals ──

	def test_case_with_errored_assertion_is_error_and_counts_judge_tokens(self):
		from one_bpmn.agents.executor import ExecutorResult, TokenUsage

		case = SimpleNamespace(
			name="case-x",
			backend="direct_api",
			provider="",
			model="m",
			input_system_prompt="",
			input_user_prompt="p",
			assertions=[_assertion("llm_judge", "rubric")],
		)

		class FakeCaseExecutor:
			def run(self, config, context):
				return ExecutorResult(
					output="case output",
					token_usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
				)

		def fake_get_executor(backend):
			return FakeCaseExecutor

		judge_result = {
			"assertion_type": "llm_judge",
			"value": "rubric",
			"passed": False,
			"error": True,
			"judge_prompt_tokens": 40,
			"judge_completion_tokens": 8,
			"judge_cost": 0.002,
			"score": 0,
			"explanation": "Judge call failed: down",
		}
		with (
			patch.object(eval_runner, "get_executor", side_effect=fake_get_executor),
			patch.object(eval_runner, "_evaluate_assertion", return_value=judge_result),
		):
			row = eval_runner._execute_case(case)

		self.assertEqual(row["status"], "Error")
		self.assertEqual(row["prompt_tokens"], 140)
		self.assertEqual(row["completion_tokens"], 28)
		self.assertEqual(row["tokens_used"], 168)
		self.assertAlmostEqual(row["cost"], 0.002)
