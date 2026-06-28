# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Unit tests for the llm_judge assertion type in eval_runner."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
from one_bpmn.agents.eval_runner import (
    JUDGE_PROMPT_TEMPLATE,
    _evaluate_assertion,
    _evaluate_llm_judge,
)


def _make_assertion(**kwargs):
    """Build a fake assertion row (SimpleNamespace mimicking a child-table row)."""
    defaults = {
        "assertion_type": "llm_judge",
        "value": "Response should be professional and helpful.",
        "judge_provider": "test-openai",
        "judge_model": "gpt-4o",
        "pass_threshold": 4,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestLlmJudgeAssertion(FrappeTestCase):
    """Tests for _evaluate_llm_judge and its integration with _evaluate_assertion."""

    # ------------------------------------------------------------------
    # Happy path: score meets threshold → pass
    # ------------------------------------------------------------------
    def test_judge_passes_when_score_meets_threshold(self):
        """AC (d): score >= pass_threshold → assertion passes."""
        judge_output = {"score": 5, "explanation": "Excellent response."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
            token_usage=TokenUsage(10, 5, 15),
        )
        assertion = _make_assertion(pass_threshold=4)

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Great answer!")

        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["explanation"], "Excellent response.")
        self.assertEqual(result["assertion_type"], "llm_judge")

    # ------------------------------------------------------------------
    # Score below threshold → fail
    # ------------------------------------------------------------------
    def test_judge_fails_when_score_below_threshold(self):
        """AC (d): score < pass_threshold → assertion fails."""
        judge_output = {"score": 2, "explanation": "Not helpful."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
            token_usage=TokenUsage(10, 5, 15),
        )
        assertion = _make_assertion(pass_threshold=4)

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Bad answer")

        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["explanation"], "Not helpful.")

    # ------------------------------------------------------------------
    # Exact threshold boundary → pass
    # ------------------------------------------------------------------
    def test_judge_passes_at_exact_threshold(self):
        """Boundary: score == pass_threshold should pass."""
        judge_output = {"score": 4, "explanation": "Meets requirements."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion(pass_threshold=4)

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Decent answer")

        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 4)

    # ------------------------------------------------------------------
    # Default threshold (4) when pass_threshold is 0/None
    # ------------------------------------------------------------------
    def test_default_threshold_is_4(self):
        """AC (d): pass_threshold defaults to 4 when not set."""
        judge_output = {"score": 4, "explanation": "Good."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion(pass_threshold=0)

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        # threshold defaults to 4 when 0/None; score 4 >= 4 → pass
        self.assertTrue(result["passed"])

    # ------------------------------------------------------------------
    # String JSON output (text response_format from executor)
    # ------------------------------------------------------------------
    def test_judge_parses_string_json_output(self):
        """Judge output may be a raw JSON string — should still parse."""
        mock_result = ExecutorResult(
            output='{"score": 5, "explanation": "Perfect."}',
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 5)

    # ------------------------------------------------------------------
    # Invalid JSON from judge
    # ------------------------------------------------------------------
    def test_judge_returns_invalid_json_string(self):
        """AC: If judge returns invalid JSON string → fails with explanation."""
        mock_result = ExecutorResult(
            output="This is not JSON at all",
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["explanation"], "Judge returned invalid JSON")

    def test_judge_returns_non_dict_json(self):
        """AC: Judge returns valid JSON but not a dict → invalid JSON."""
        mock_result = ExecutorResult(
            output=[1, 2, 3],  # list, not dict
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        self.assertFalse(result["passed"])
        self.assertEqual(result["explanation"], "Judge returned invalid JSON")

    def test_judge_returns_non_integer_score(self):
        """AC: Judge returns a non-integer score → invalid JSON."""
        mock_result = ExecutorResult(
            output={"score": "high", "explanation": "Good"},
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        self.assertFalse(result["passed"])
        self.assertEqual(result["explanation"], "Judge returned invalid JSON")

    # ------------------------------------------------------------------
    # Executor error
    # ------------------------------------------------------------------
    def test_executor_error_returns_failure(self):
        """AC: If executor returns an error → assertion fails with explanation."""
        mock_result = ExecutorResult(
            error_code=ErrorCode.FAILED_MODEL_CALL,
            error_message="Connection refused",
        )
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(
            result["explanation"], "Judge call failed: Connection refused"
        )

    def test_executor_exception_returns_failure(self):
        """AC: If executor raises an exception → assertion fails."""
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.side_effect = RuntimeError("Boom")
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 0)
        self.assertIn("Judge call failed:", result["explanation"])
        self.assertIn("Boom", result["explanation"])

    # ------------------------------------------------------------------
    # Prompt template construction
    # ------------------------------------------------------------------
    def test_judge_prompt_template_contains_rubric_and_output(self):
        """AC (a): Judge prompt is constructed from the template with rubric and output."""
        judge_output = {"score": 5, "explanation": "Good."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion(value="Be polite and concise.")

        captured_config = {}

        def capture_run(config, context):
            captured_config["user_prompt"] = config.user_prompt
            captured_config["system_prompt"] = config.system_prompt
            captured_config["response_format"] = config.response_format
            captured_config["provider_name"] = config.provider_name
            captured_config["model"] = config.model
            return mock_result

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor_cls = MagicMock()
            mock_executor_instance = MagicMock()
            mock_executor_instance.run.side_effect = capture_run
            mock_executor_cls.return_value = mock_executor_instance
            mock_get.return_value = mock_executor_cls

            _evaluate_llm_judge(assertion, "Hello, thank you!")

        # AC (a): Prompt contains rubric and output
        self.assertIn("Be polite and concise.", captured_config["user_prompt"])
        self.assertIn("Hello, thank you!", captured_config["user_prompt"])

        # AC (b): system_prompt is empty
        self.assertEqual(captured_config["system_prompt"], "")

        # AC (b): response_format is json
        self.assertEqual(captured_config["response_format"], "json")

        # AC (b): provider and model come from assertion
        self.assertEqual(captured_config["provider_name"], "test-openai")
        self.assertEqual(captured_config["model"], "gpt-4o")

    # ------------------------------------------------------------------
    # Result schema (AC e)
    # ------------------------------------------------------------------
    def test_result_includes_required_fields(self):
        """AC (e): assertion_results entry includes type, passed, score, explanation."""
        judge_output = {"score": 3, "explanation": "Somewhat helpful."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion(pass_threshold=4)

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_llm_judge(assertion, "Answer")

        # All required keys present
        self.assertIn("assertion_type", result)
        self.assertIn("passed", result)
        self.assertIn("score", result)
        self.assertIn("explanation", result)
        self.assertEqual(result["assertion_type"], "llm_judge")
        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 3)
        self.assertEqual(result["explanation"], "Somewhat helpful.")

    # ------------------------------------------------------------------
    # Integration: _evaluate_assertion dispatches to llm_judge
    # ------------------------------------------------------------------
    def test_evaluate_assertion_dispatches_llm_judge(self):
        """The top-level _evaluate_assertion correctly dispatches to llm_judge."""
        judge_output = {"score": 5, "explanation": "Perfect."}
        mock_result = ExecutorResult(
            output=judge_output,
            error_code=ErrorCode.SUCCESS,
        )
        assertion = _make_assertion()

        with patch(
            "one_bpmn.agents.eval_runner.get_executor"
        ) as mock_get:
            mock_executor = MagicMock()
            mock_executor.return_value.run.return_value = mock_result
            mock_get.return_value = mock_executor
            result = _evaluate_assertion(assertion, "Answer")

        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 5)

    # ------------------------------------------------------------------
    # Prompt template constant
    # ------------------------------------------------------------------
    def test_judge_prompt_template_structure(self):
        """JUDGE_PROMPT_TEMPLATE contains the required placeholders."""
        self.assertIn("{rubric}", JUDGE_PROMPT_TEMPLATE)
        self.assertIn("{actual_output}", JUDGE_PROMPT_TEMPLATE)
        self.assertIn("Score the response from 1 to 5", JUDGE_PROMPT_TEMPLATE)
        self.assertIn("Respond with ONLY a JSON object", JUDGE_PROMPT_TEMPLATE)
