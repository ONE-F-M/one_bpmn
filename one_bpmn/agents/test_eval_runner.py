# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the eval runner: suite execution, the contains/regex/equals/
schema_valid assertion types, per-case error isolation, and final run status.

The executor is always mocked — no real LLM call is made.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_runner import _execute_eval_suite, run_eval_suite
from one_bpmn.agents._eval_test_factories import (
    make_eval_case,
    make_eval_run,
    make_eval_suite,
    patch_executor,
    success_result,
)


class TestEvalRunner(FrappeTestCase):

    # -- run_eval_suite entry point -------------------------------------

    def test_run_eval_suite_creates_running_run(self):
        """(a) run_eval_suite() creates a Running run and returns its name."""
        suite = make_eval_suite()
        make_eval_case(suite=suite.name)

        with patch("frappe.enqueue") as mock_enqueue:
            run_name = run_eval_suite(suite.name)

        mock_enqueue.assert_called_once()
        run = frappe.get_doc("AI Eval Run", run_name)
        self.assertEqual(run.status, "Running")
        self.assertEqual(run.suite, suite.name)
        self.assertEqual(run.backend, "live")

    def test_run_eval_suite_missing_suite_throws(self):
        """run_eval_suite() throws for an unknown suite name."""
        self.assertRaises(
            frappe.ValidationError, run_eval_suite, "does-not-exist"
        )

    # -- assertion types ------------------------------------------------

    def _run_single_case(self, output, assertions):
        """Build a one-case suite, execute it, return the single result row."""
        suite = make_eval_suite()
        make_eval_case(suite=suite.name, assertions=assertions)
        run = make_eval_run(suite.name)

        with patch_executor(success_result(output)):
            _execute_eval_suite(run.name)

        run.reload()
        self.assertEqual(len(run.results), 1)
        return run, run.results[0]

    def test_contains_assertion_passes(self):
        """(b) contains assertion passes when the substring is present."""
        run, result = self._run_single_case(
            "approved", [{"assertion_type": "contains", "value": "approved"}]
        )
        self.assertEqual(result.status, "Passed")
        self.assertEqual(run.status, "Passed")

    def test_regex_assertion_passes(self):
        """(c) regex ^\\{ passes when output starts with '{'."""
        _, result = self._run_single_case(
            '{"ok": true}', [{"assertion_type": "regex", "value": r"^\{"}]
        )
        self.assertEqual(result.status, "Passed")

    def test_equals_assertion_passes(self):
        """(d) equals passes when output matches exactly."""
        _, result = self._run_single_case(
            "yes", [{"assertion_type": "equals", "value": "yes"}]
        )
        self.assertEqual(result.status, "Passed")

    def test_schema_valid_assertion_passes(self):
        """(e) schema_valid passes when output validates against the schema."""
        schema = json.dumps(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            }
        )
        _, result = self._run_single_case(
            {"name": "Kartik"},
            [{"assertion_type": "schema_valid", "value": schema}],
        )
        self.assertEqual(result.status, "Passed")

    def test_contains_assertion_fails(self):
        """(f) contains fails when the substring is not found."""
        run, result = self._run_single_case(
            "denied", [{"assertion_type": "contains", "value": "approved"}]
        )
        self.assertEqual(result.status, "Failed")
        self.assertEqual(run.status, "Failed")
        # The failure reason is recorded in the assertion results JSON.
        assertion_results = json.loads(result.assertion_results)
        self.assertFalse(assertion_results[0]["passed"])

    # -- error isolation ------------------------------------------------

    def test_executor_error_is_isolated(self):
        """(g) one erroring case yields Error but the runner continues."""
        suite = make_eval_suite()
        boom = make_eval_case(
            suite=suite.name,
            input_user_prompt="please explode now",
        )
        ok = make_eval_case(
            suite=suite.name,
            input_user_prompt="behave",
            assertions=[{"assertion_type": "contains", "value": "approved"}],
        )
        run = make_eval_run(suite.name)

        def handler(config, context):
            if "explode" in (config.user_prompt or ""):
                raise RuntimeError("executor crashed")
            return success_result("approved")

        with patch_executor(handler):
            _execute_eval_suite(run.name)

        run.reload()
        by_case = {r.eval_case: r for r in run.results}
        self.assertEqual(len(run.results), 2, "both cases must be recorded")
        self.assertEqual(by_case[boom.name].status, "Error")
        self.assertEqual(by_case[ok.name].status, "Passed")
        self.assertTrue(by_case[boom.name].error_message)

    # -- final run status ----------------------------------------------

    def test_run_status_passed_when_all_pass(self):
        """(h) run status is Passed when every case passes."""
        suite = make_eval_suite()
        make_eval_case(
            suite=suite.name,
            assertions=[{"assertion_type": "contains", "value": "approved"}],
        )
        make_eval_case(
            suite=suite.name,
            assertions=[{"assertion_type": "equals", "value": "approved"}],
        )
        run = make_eval_run(suite.name)

        with patch_executor(success_result("approved")):
            _execute_eval_suite(run.name)

        run.reload()
        self.assertEqual(run.status, "Passed")
        self.assertEqual(run.total_cases, 2)
        self.assertEqual(run.passed_cases, 2)
        self.assertEqual(run.failed_cases, 0)

    def test_run_status_failed_when_any_fails(self):
        """(h) run status is Failed when any case fails."""
        suite = make_eval_suite()
        make_eval_case(
            suite=suite.name,
            assertions=[{"assertion_type": "contains", "value": "approved"}],
        )
        make_eval_case(
            suite=suite.name,
            assertions=[{"assertion_type": "contains", "value": "rejected"}],
        )
        run = make_eval_run(suite.name)

        with patch_executor(success_result("approved")):
            _execute_eval_suite(run.name)

        run.reload()
        self.assertEqual(run.status, "Failed")
        self.assertEqual(run.total_cases, 2)
        self.assertEqual(run.passed_cases, 1)
        self.assertEqual(run.failed_cases, 1)
