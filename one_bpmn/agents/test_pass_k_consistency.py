# Copyright (c) 2026, one-fm and contributors
"""Running a case k times, reporting consistency, and blocking on the pass rate.

One run of a flaky agent is a coin toss. An agent that deviates in two turns out
of five passes a single run three times in five, and the go-live gate then means
nothing. So a suite can declare how many times each case runs and the rate it
must clear, and those two numbers are what the gate reads.

The executor is mocked: what matters here is the arithmetic and the decisions
taken from it, not any model's answer. Each test says which sequence of
pass/fail it feeds, because that sequence IS the scenario.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.agents.eval_runner import _execute_eval_suite

RUNNER_CASE = "one_bpmn.agents.eval_runner._execute_case"


def _run_doc(suite: str, backend: str = "live"):
	run = frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite,
		"status": "Running",
		"backend": backend,
		"scope": "Suite",
		"started_at": frappe.utils.now_datetime(),
	})
	run.flags.ignore_mandatory = True
	run.flags.ignore_links = True
	return run.insert(ignore_permissions=True)


def _results(statuses):
	"""An executor that returns the given statuses in order, then repeats the last."""
	sequence = list(statuses)

	def fake(case, eval_run=None, agent_cfg=None):
		status = sequence.pop(0) if sequence else statuses[-1]
		return {
			"eval_case": case.name,
			"status": status,
			"actual_output": f"answer ({status})",
			"assertion_results": "[]",
			"error_message": "" if status == "Passed" else "an assertion failed",
			"cost": 0.01,
			"tokens_used": 100,
			"prompt_tokens": 80,
			"completion_tokens": 20,
		}

	return fake


class TestPassK(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test pass_k " + frappe.generate_hash(length=6))
		self.case = make_eval_case(suite=self.suite.name, title="_Test case")

	def _execute(self, statuses, pass_k=1, min_pass_rate=0, backend="live"):
		self.suite.db_set("pass_k", pass_k, update_modified=False)
		self.suite.db_set("min_pass_rate", min_pass_rate, update_modified=False)
		run = _run_doc(self.suite.name, backend)
		with patch(RUNNER_CASE, new=_results(statuses)):
			_execute_eval_suite(run.name)
		run.reload()
		return run

	def test_each_case_executes_pass_k_times(self):
		run = self._execute(["Passed"] * 4, pass_k=4)
		self.assertEqual(run.results[0].runs, 4)
		self.assertEqual(run.results[0].passes, 4)
		self.assertEqual(run.total_executions, 4)
		self.assertEqual(run.status, "Passed")

	def test_one_failure_out_of_four_fails_the_case(self):
		"""The fourth run is the one a user would have hit."""
		run = self._execute(["Passed", "Passed", "Failed", "Passed"], pass_k=4)
		row = run.results[0]
		self.assertEqual(row.status, "Failed")
		self.assertEqual(row.passes, 3)
		self.assertEqual(row.runs, 4)
		self.assertEqual(row.consistency_rate, 75)
		self.assertEqual(run.failed_cases, 1)
		self.assertEqual(run.status, "Failed")

	def test_a_flaky_case_says_so_on_the_row(self):
		run = self._execute(["Passed", "Failed", "Passed", "Passed"], pass_k=4)
		self.assertIn("Flaky: passed 3 of 4 runs", run.results[0].error_message)

	def test_the_failing_execution_is_the_one_recorded(self):
		"""A reviewer needs the run that went wrong, not the one that went well."""
		run = self._execute(["Passed", "Failed", "Passed"], pass_k=3)
		self.assertIn("Failed", run.results[0].actual_output)

	def test_spend_is_summed_over_every_execution(self):
		run = self._execute(["Passed"] * 3, pass_k=3)
		self.assertEqual(run.results[0].tokens_used, 300)
		self.assertAlmostEqual(run.results[0].cost, 0.03, places=6)
		self.assertEqual(run.total_tokens, 300)

	def test_the_pass_rate_is_over_executions_not_cases(self):
		make_eval_case(suite=self.suite.name, title="_Test second case")
		# first case passes twice, second fails once then passes
		run = self._execute(["Passed", "Passed", "Failed", "Passed"], pass_k=2)
		self.assertEqual(run.total_cases, 2)
		self.assertEqual(run.total_executions, 4)
		self.assertEqual(run.pass_rate, 75)

	def test_a_single_run_per_case_behaves_exactly_as_before(self):
		run = self._execute(["Passed"], pass_k=1)
		self.assertEqual(run.results[0].runs, 1)
		self.assertEqual(run.pass_rate, 100)
		self.assertEqual(run.status, "Passed")

	def test_a_replay_never_repeats_the_stored_answer(self):
		"""Re-scoring one stored answer k times would report a consistency the
		run never demonstrated."""
		self.case.db_set("expected_output", "x", update_modified=False)
		run = self._execute(["Passed"] * 4, pass_k=4, backend="replay")
		self.assertEqual(run.results[0].runs, 1)

	def test_a_suite_below_its_minimum_rate_fails_even_with_no_failed_case(self):
		"""The rate is a second bar, not a restatement of the first: a suite can
		be told to fail on a rate its per-case rule would have allowed."""
		run = self._execute(["Passed"], pass_k=1, min_pass_rate=100)
		self.assertEqual(run.status, "Passed")

		run = self._execute(["Passed", "Failed"], pass_k=2, min_pass_rate=90)
		self.assertEqual(run.pass_rate, 50)
		self.assertEqual(run.status, "Failed")
