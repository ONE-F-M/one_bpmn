# Copyright (c) 2026, one-fm and contributors
"""The deterministic backend, and the verdict a CI check is built on.

A pull-request check has to answer without a provider key, so it scores each
case's assertions against the answer recorded on the case and calls no model at
all. What that catches is a break in the scoring layer — an evaluator that stops
matching, an assertion that changes meaning. What it cannot catch is the agent
drifting, which is why the live suites run nightly.

Most of these tests are about the two ways such a check lies: failing a case
because CI has no key, and passing a suite that verified nothing.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.agents.eval_runner import (
	MODEL_BACKED_ASSERTIONS,
	_execute_case_deterministic,
	_execute_eval_suite,
)
from one_bpmn.agents.eval_ci import _why
from one_bpmn.commands.evals import _verdict

JUDGE = "one_bpmn.agents.eval_runner._evaluate_llm_judge"


def _case(**kwargs):
	case = make_eval_case(**kwargs)
	case.reload()
	return case


class TestDeterministicScoring(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test deterministic " + frappe.generate_hash(length=6))

	def _with(self, answer, assertions):
		case = _case(suite=self.suite.name, expected_output=answer)
		case.set("assertions", assertions)
		case.flags.ignore_mandatory = True
		case.save(ignore_permissions=True)
		case.reload()
		return case

	def test_it_scores_the_answer_recorded_on_the_case(self):
		case = self._with("The connector is disabled.", [{"assertion_type": "contains", "value": "disabled"}])
		row = _execute_case_deterministic(case)
		self.assertEqual(row["status"], "Passed")
		self.assertEqual(row["actual_output"], "The connector is disabled.")

	def test_a_failing_assertion_fails_the_case(self):
		case = self._with("The connector is enabled.", [{"assertion_type": "contains", "value": "disabled"}])
		row = _execute_case_deterministic(case)
		self.assertEqual(row["status"], "Failed")
		self.assertIn("Substring not found", row["assertion_results"])

	def test_it_never_calls_a_model(self):
		"""The whole point: a pull request check with no provider key."""
		case = self._with(
			"ready",
			[
				{"assertion_type": "equals", "value": "ready"},
				{"assertion_type": "llm_judge", "value": "is it ready?",
				 "judge_provider": "Anthropic", "judge_model": "claude-haiku-4-5-20251001"},
			],
		)
		with patch(JUDGE) as judge:
			row = _execute_case_deterministic(case)
		judge.assert_not_called()
		self.assertEqual(row["status"], "Passed")

	def test_an_assertion_needing_a_model_is_skipped_and_said_so(self):
		case = self._with(
			"ready",
			[
				{"assertion_type": "equals", "value": "ready"},
				{"assertion_type": "llm_judge", "value": "rubric",
				 "judge_provider": "Anthropic", "judge_model": "claude-haiku-4-5-20251001"},
			],
		)
		row = _execute_case_deterministic(case)
		self.assertIn("Skipped llm_judge", row["error_message"])
		self.assertNotIn("llm_judge", row["assertion_results"])

	def test_a_case_whose_every_assertion_needs_a_model_is_skipped_not_failed(self):
		"""Failing it would turn "CI has no key" into a red check on every PR."""
		case = self._with(
			"anything",
			[{"assertion_type": "llm_judge", "value": "rubric",
			  "judge_provider": "Anthropic", "judge_model": "claude-haiku-4-5-20251001"}],
		)
		row = _execute_case_deterministic(case)
		self.assertEqual(row["status"], "Skipped")
		self.assertIn("nothing to check", row["error_message"])

	def test_a_case_with_no_recorded_answer_is_skipped_with_advice(self):
		case = self._with("", [{"assertion_type": "contains", "value": "x"}])
		row = _execute_case_deterministic(case)
		self.assertEqual(row["status"], "Skipped")
		self.assertIn("records no expected output", row["error_message"])

	def test_it_falls_back_to_the_last_stored_answer(self):
		"""A suite captured from real runs has no expected output, but it does
		have what the agent said last time."""
		case = self._with("", [{"assertion_type": "contains", "value": "frankfurter"}])
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": "Passed",
			"backend": "live", "started_at": frappe.utils.now_datetime(),
			"results": [{
				"eval_case": case.name, "status": "Passed",
				"actual_output": "built the frankfurter connector",
			}],
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)

		row = _execute_case_deterministic(case)
		self.assertEqual(row["status"], "Passed")
		self.assertIn("last stored answer", row["error_message"])

	def test_a_broken_assertion_is_an_error_not_a_pass(self):
		case = self._with("ready", [{"assertion_type": "regex", "value": "([unclosed"}])
		row = _execute_case_deterministic(case)
		self.assertEqual(row["status"], "Error")

	def test_it_costs_nothing(self):
		case = self._with("ready", [{"assertion_type": "equals", "value": "ready"}])
		row = _execute_case_deterministic(case)
		self.assertEqual(row["cost"], 0)
		self.assertEqual(row["tokens_used"], 0)

	def test_only_llm_judge_is_treated_as_needing_a_model(self):
		"""If a new model-backed assertion type is added, it belongs in that set
		— this is the reminder."""
		self.assertEqual(MODEL_BACKED_ASSERTIONS, {"llm_judge"})


class TestSuiteRunDeterministic(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test det suite " + frappe.generate_hash(length=6))

	def _case(self, answer, assertions):
		case = _case(suite=self.suite.name, expected_output=answer)
		case.set("assertions", assertions)
		case.flags.ignore_mandatory = True
		case.save(ignore_permissions=True)
		return case

	def _run(self):
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": "Running",
			"backend": "deterministic", "scope": "Suite", "started_at": frappe.utils.now_datetime(),
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)
		_execute_eval_suite(run.name)
		run.reload()
		return run

	def test_a_skipped_case_counts_as_neither_pass_nor_failure(self):
		self._case("ready", [{"assertion_type": "equals", "value": "ready"}])
		self._case("x", [{"assertion_type": "llm_judge", "value": "r",
						  "judge_provider": "Anthropic", "judge_model": "claude-haiku-4-5-20251001"}])
		run = self._run()
		self.assertEqual(run.total_cases, 2)
		self.assertEqual(run.passed_cases, 1)
		self.assertEqual(run.failed_cases, 0)
		self.assertEqual(run.status, "Passed")

	def test_a_failing_case_fails_the_run(self):
		self._case("ready", [{"assertion_type": "equals", "value": "ready"}])
		self._case("nope", [{"assertion_type": "equals", "value": "ready"}])
		run = self._run()
		self.assertEqual(run.failed_cases, 1)
		self.assertEqual(run.status, "Failed")

	def test_the_run_records_the_backend_it_used(self):
		self._case("ready", [{"assertion_type": "equals", "value": "ready"}])
		self.assertEqual(self._run().backend, "deterministic")


class TestCommandVerdict(FrappeTestCase):
	"""What turns a run into a red or green check."""

	def _summary(self, **kwargs):
		base = {"suite": "S", "run": "r", "status": "Passed", "cases": 4,
				"checked": 4, "passed": 4, "skipped": 0, "rate": 100.0, "failures": []}
		base.update(kwargs)
		return base

	def test_at_or_above_the_minimum_passes(self):
		self.assertFalse(_verdict([self._summary(rate=100.0)], 100, False))
		self.assertFalse(_verdict([self._summary(rate=91.0)], 90, False))

	def test_below_the_minimum_fails(self):
		self.assertTrue(_verdict([self._summary(rate=89.9, passed=3)], 90, False))

	def test_one_failing_suite_fails_the_whole_check(self):
		self.assertTrue(_verdict([self._summary(), self._summary(suite="T", rate=10.0)], 90, False))

	def test_a_suite_that_checked_nothing_fails_by_default(self):
		"""A green check that verified nothing is worse than a red one."""
		self.assertTrue(_verdict([self._summary(rate=None, checked=0, passed=0, skipped=4)], 100, False))

	def test_checked_nothing_can_be_allowed_explicitly(self):
		self.assertFalse(_verdict([self._summary(rate=None, checked=0, passed=0, skipped=4)], 100, True))


class TestFailureLine(FrappeTestCase):
	"""A CI log is read once, in a hurry, by someone who did not write the case."""

	def test_it_names_the_assertion_that_did_not_hold(self):
		result = frappe._dict(
			assertion_results=json.dumps([
				{"assertion_type": "contains", "value": "disabled", "passed": False,
				 "message": "Substring not found."},
				{"assertion_type": "regex", "value": "x", "passed": True},
			]),
			error_message="Scored against the case's recorded answer, no model call.",
		)
		why = _why(result)
		self.assertIn("contains", why)
		self.assertIn("disabled", why)
		self.assertIn("Substring not found", why)
		self.assertNotIn("regex", why, "a passing assertion is not the reason")

	def test_it_falls_back_to_the_row_note(self):
		result = frappe._dict(assertion_results="[]", error_message="Nothing to replay.")
		self.assertEqual(_why(result), "Nothing to replay.")

	def test_malformed_assertion_results_do_not_crash_the_report(self):
		result = frappe._dict(assertion_results="not json", error_message="something went wrong")
		self.assertEqual(_why(result), "something went wrong")

	def test_a_row_with_nothing_recorded_still_says_something(self):
		result = frappe._dict(assertion_results="[]", error_message="")
		self.assertEqual(_why(result), "no detail recorded")
