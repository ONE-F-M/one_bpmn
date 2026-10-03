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
from frappe.utils import now_datetime

from one_bpmn.agents._eval_test_factories import (
    make_agent_configuration,
    make_eval_case,
    make_eval_run,
    make_eval_suite,
    patch_executor,
    success_result,
)
from one_bpmn.agents.eval_runner import (
    _execute_case,
    _execute_eval_suite,
    _mark_expected_errors,
    run_eval_cases,
    run_eval_suite,
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

    # -- run_eval_cases (WI-001746) -------------------------------------

    def test_run_eval_cases_subset_passes_case_names(self):
        """run_eval_cases() enqueues only the chosen cases."""
        suite = make_eval_suite()
        c1 = make_eval_case(suite=suite.name)
        make_eval_case(suite=suite.name)  # not selected

        with patch("frappe.enqueue") as mock_enqueue:
            run_name = run_eval_cases(suite.name, case_names=json.dumps([c1.name]))

        self.assertTrue(run_name)
        _, kwargs = mock_enqueue.call_args
        self.assertEqual(kwargs["case_names"], [c1.name])

    def test_run_eval_cases_rejects_foreign_case(self):
        """A case that does not belong to the suite is rejected.

        Asserting on the message matters here: run_eval_cases also throws
        ValidationError for an agent-less suite, so a bare assertRaises passed
        for the wrong reason while the fixtures had no agent configuration.
        """
        suite = make_eval_suite()
        other = make_eval_case()  # no suite / different suite
        with self.assertRaises(frappe.ValidationError) as ctx:
            run_eval_cases(suite.name, json.dumps([other.name]))
        self.assertIn(other.name, str(ctx.exception))

    def test_run_eval_cases_rejects_suite_without_agent(self):
        """A live run needs an agent to evaluate (WI-001751)."""
        suite = make_eval_suite(agent_configuration=None)
        make_eval_case(suite=suite.name)
        with self.assertRaises(frappe.ValidationError) as ctx:
            run_eval_cases(suite.name)
        self.assertIn("agent configuration", str(ctx.exception))

    def test_replay_run_skips_the_agent_requirement(self):
        """Replay does not call the agent, so it must not demand one."""
        suite = make_eval_suite(agent_configuration=None)
        make_eval_case(suite=suite.name)
        with patch("frappe.enqueue"):
            self.assertTrue(run_eval_cases(suite.name, backend="replay"))

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


def _make_agent_run(case: str, eval_run: str, errors: list[tuple[str | None, str | None]]) -> str:
    """An AI Agent Run tagged to *case* and *eval_run*, with one step per (error_code, error_message)."""
    run = frappe.get_doc({
        "doctype": "AI Agent Run",
        "bpmn_id": "Activity_test",
        "status": "Success",
        "started_at": now_datetime(),
        "element_type": "task",
        "origin": "eval",
        "eval_case": case,
        "eval_run": eval_run,
    })
    run.flags.ignore_mandatory = True
    run.flags.ignore_links = True
    run.insert(ignore_permissions=True)
    for index, (code, message) in enumerate(errors, start=1):
        step = frappe.get_doc({
            "doctype": "AI Agent Step",
            "run": run.name,
            "step_index": index,
            "role": "tool",
            "content": "",
            "error_code": code,
            "error_message": message,
        })
        step.flags.ignore_mandatory = True
        step.flags.ignore_links = True
        step.insert(ignore_permissions=True)
    return run.name


def _flags(agent_run: str) -> list[int]:
    return frappe.get_all(
        "AI Agent Step", filters={"run": agent_run}, pluck="is_expected_error", order_by="step_index asc"
    )


class TestEvalAttributionAndExpectedErrors(FrappeTestCase):

    def _process_model(self, configurations: int) -> str:
        model = "_Test Eval Map " + frappe.generate_hash(length=8)
        for _ in range(configurations):
            make_agent_configuration(process_model=model)
        return model

    def _agentless_suite(self, configurations: int):
        return make_eval_suite(agent_configuration=None, process_model=self._process_model(configurations))

    # -- agent_configuration fallback ------------------------------------

    def test_run_takes_the_only_configuration_on_the_suite_process_model(self):
        suite = self._agentless_suite(configurations=1)
        expected = frappe.get_value("AI Agent Configuration", {"process_model": suite.process_model}, "name")

        with patch("frappe.enqueue"):
            run_name = run_eval_suite(suite.name)

        self.assertEqual(frappe.db.get_value("AI Eval Run", run_name, "agent_configuration"), expected)

    def test_run_stays_unattributed_when_no_configuration_matches(self):
        suite = self._agentless_suite(configurations=0)

        with patch("frappe.enqueue"):
            run_name = run_eval_suite(suite.name)

        self.assertFalse(frappe.db.get_value("AI Eval Run", run_name, "agent_configuration"))

    def test_run_stays_unattributed_when_several_configurations_match(self):
        suite = self._agentless_suite(configurations=2)

        with patch("frappe.enqueue"):
            run_name = run_eval_suite(suite.name)

        self.assertFalse(frappe.db.get_value("AI Eval Run", run_name, "agent_configuration"))

    def test_suite_agent_wins_over_the_process_model(self):
        own = make_agent_configuration()
        suite = make_eval_suite(agent_configuration=own.name, process_model=self._process_model(configurations=1))

        with patch("frappe.enqueue"):
            run_name = run_eval_suite(suite.name)

        self.assertEqual(frappe.db.get_value("AI Eval Run", run_name, "agent_configuration"), own.name)

    def test_live_run_eval_cases_accepts_a_suite_resolved_through_its_process_model(self):
        suite = self._agentless_suite(configurations=1)
        expected = frappe.get_value("AI Agent Configuration", {"process_model": suite.process_model}, "name")

        with patch("frappe.enqueue"):
            run_name = run_eval_cases(suite.name, backend="live")

        self.assertEqual(frappe.db.get_value("AI Eval Run", run_name, "agent_configuration"), expected)

    def test_live_run_eval_cases_still_refuses_an_unresolvable_suite(self):
        suite = self._agentless_suite(configurations=2)

        with patch("frappe.enqueue"):
            self.assertRaises(frappe.ValidationError, run_eval_cases, suite.name, None, "live")

    # -- expected errors -------------------------------------------------

    def test_only_the_matching_step_error_is_marked_expected(self):
        suite = make_eval_suite()
        case = make_eval_case(suite=suite.name, expected_error="get_pull_request")
        eval_run = make_eval_run(suite.name).name
        agent_run = _make_agent_run(case.name, eval_run, [
            ("TOOL_ERROR", "get_pull_request: 404 Not Found"),
            ("TOOL_ERROR", "list_work_items: connection reset"),
            (None, None),
        ])

        flagged = _mark_expected_errors(case.name, case.expected_error, eval_run)

        self.assertEqual(flagged, 1)
        self.assertEqual(_flags(agent_run), [1, 0, 0])
        self.assertEqual(_mark_expected_errors(case.name, case.expected_error, eval_run), 0)

    def test_a_case_without_expected_error_marks_nothing(self):
        suite = make_eval_suite()
        case = make_eval_case(suite=suite.name)
        eval_run = make_eval_run(suite.name).name
        agent_run = _make_agent_run(case.name, eval_run, [("TOOL_ERROR", "get_pull_request: 404 Not Found")])

        self.assertEqual(_mark_expected_errors(case.name, case.expected_error, eval_run), 0)
        self.assertEqual(_flags(agent_run), [0])

    def test_another_eval_run_of_the_same_case_is_left_alone(self):
        suite = make_eval_suite()
        case = make_eval_case(suite=suite.name, expected_error="get_pull_request")
        this_run = make_eval_run(suite.name).name
        other_run = make_eval_run(suite.name).name
        other_agent_run = _make_agent_run(case.name, other_run, [("TOOL_ERROR", "get_pull_request: 404")])

        _mark_expected_errors(case.name, case.expected_error, this_run)

        self.assertEqual(_flags(other_agent_run), [0])

    def test_executing_a_case_marks_its_expected_errors(self):
        suite = make_eval_suite()
        case = make_eval_case(suite=suite.name, expected_error="get_pull_request")
        eval_run = make_eval_run(suite.name).name
        made = {}

        def run_the_agent(case_doc, run_name, agent_cfg):
            made["run"] = _make_agent_run(case_doc.name, run_name, [("TOOL_ERROR", "get_pull_request: 404")])
            return {"eval_case": case_doc.name, "status": "Passed"}

        with patch("one_bpmn.agents.eval_runner._execute_case_inner", side_effect=run_the_agent):
            _execute_case(frappe.get_doc("AI Eval Case", case.name), eval_run)

        self.assertEqual(_flags(made["run"]), [1])

    # -- backfill patch --------------------------------------------------

    def test_patch_attributes_old_runs_and_marks_past_errors_and_is_idempotent(self):
        from one_bpmn.one_bpmn.patches.v1_0 import (
            eval_runs_name_their_agent_and_expected_errors_are_marked as backfill,
        )

        resolvable = self._agentless_suite(configurations=1)
        ambiguous = self._agentless_suite(configurations=2)
        expected = frappe.get_value("AI Agent Configuration", {"process_model": resolvable.process_model}, "name")
        old_run = make_eval_run(resolvable.name).name
        stuck_run = make_eval_run(ambiguous.name).name
        case = make_eval_case(suite=resolvable.name, expected_error="get_pull_request")
        agent_run = _make_agent_run(case.name, old_run, [
            ("TOOL_ERROR", "get_pull_request: 404"), ("TOOL_ERROR", "get_work_item: timeout"),
        ])

        backfill.execute()
        backfill.execute()

        self.assertEqual(frappe.db.get_value("AI Eval Suite", resolvable.name, "agent_configuration"), expected)
        self.assertEqual(frappe.db.get_value("AI Eval Run", old_run, "agent_configuration"), expected)
        self.assertFalse(frappe.db.get_value("AI Eval Suite", ambiguous.name, "agent_configuration"))
        self.assertFalse(frappe.db.get_value("AI Eval Run", stuck_run, "agent_configuration"))
        self.assertEqual(_flags(agent_run), [1, 0])
