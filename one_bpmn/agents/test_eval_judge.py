# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the llm_judge assertion handler.

Covers score-based pass/fail, custom thresholds, invalid JSON,
executor errors, and prompt template formatting.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
	ErrorCode,
	ExecutorResult,
	TokenUsage,
)
from one_bpmn.agents.eval_runner import (
	_assert_llm_judge,
	_evaluate_assertions,
	JUDGE_PROMPT_TEMPLATE,
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

	# ── AC (a): Score meets threshold → pass ──────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_pass_above_threshold(self, mock_get):
		"""An llm_judge assertion with score=5 and pass_threshold=4 passes."""
		mock_get.return_value = self._mock_success(score=5, explanation="Great response")
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row(threshold=4))
		self.assertTrue(result["passed"])
		self.assertEqual(result["score"], 5)
		self.assertEqual(result["explanation"], "Great response")
		self.assertEqual(result["type"], "llm_judge")

	# ── AC (b): Score below threshold → fail ──────────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_fail_below_threshold(self, mock_get):
		"""An llm_judge assertion with score=2 and pass_threshold=4 fails."""
		mock_get.return_value = self._mock_success(score=2, explanation="Poor output")
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row(threshold=4))
		self.assertFalse(result["passed"])
		self.assertEqual(result["score"], 2)

	# ── AC (c): Invalid JSON → fails gracefully ──────────────────────

	@patch("one_bpmn.agents.eval_runner.get_executor")
	def test_llm_judge_invalid_json_fails_gracefully(self, mock_get):
		"""An llm_judge assertion with invalid judge JSON fails gracefully."""
		mock = MagicMock()
		mock.return_value.run.return_value = ExecutorResult(
			output="not valid json at all",
			error_code=ErrorCode.SUCCESS,
		)
		mock_get.return_value = mock
		result = _assert_llm_judge("AI output", "Be helpful", self._make_row())
		self.assertFalse(result["passed"])
		self.assertEqual(result["score"], 0)
		self.assertEqual(result["explanation"], "Judge returned invalid JSON")

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
