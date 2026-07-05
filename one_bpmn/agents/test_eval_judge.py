# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the llm_judge assertion type.

The judge LLM call goes through the same executor infrastructure, so it is
mocked. The judge "returns" a JSON object describing a score; the assertion
passes when the score meets the threshold and fails gracefully on bad JSON.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_runner import _evaluate_assertion
from one_bpmn.agents._eval_test_factories import patch_executor, success_result


def _judge_assertion(value="Is the response polite?", pass_threshold=4):
    """Build a lightweight llm_judge assertion object."""
    return frappe._dict(
        assertion_type="llm_judge",
        value=value,
        judge_provider="",
        judge_model="judge-model",
        pass_threshold=pass_threshold,
    )


class TestEvalJudge(FrappeTestCase):

    def test_judge_passes_above_threshold(self):
        """(a) score 5 passes when pass_threshold=4."""
        assertion = _judge_assertion(pass_threshold=4)
        judge_output = '{"score": 5, "explanation": "Very polite."}'

        with patch_executor(success_result(judge_output)):
            result = _evaluate_assertion(assertion, "Thank you, please proceed.")

        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["assertion_type"], "llm_judge")

    def test_judge_fails_below_threshold(self):
        """(b) score 2 fails when pass_threshold=4."""
        assertion = _judge_assertion(pass_threshold=4)
        judge_output = '{"score": 2, "explanation": "Rude."}'

        with patch_executor(success_result(judge_output)):
            result = _evaluate_assertion(assertion, "Go away.")

        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 2)

    def test_judge_passes_when_output_already_dict(self):
        """A judge returning a parsed dict (json response_format) also works."""
        assertion = _judge_assertion(pass_threshold=4)
        judge_output = {"score": 4, "explanation": "Acceptable."}

        with patch_executor(success_result(judge_output)):
            result = _evaluate_assertion(assertion, "Sure thing.")

        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 4)

    def test_judge_invalid_json_fails_gracefully(self):
        """(c) invalid judge JSON fails without raising."""
        assertion = _judge_assertion(pass_threshold=4)

        with patch_executor(success_result("not json at all {")):
            result = _evaluate_assertion(assertion, "whatever")

        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 0)
        self.assertIn("invalid JSON", result["explanation"])
