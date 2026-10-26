# Copyright (c) 2026, one-fm and contributors
"""What the overnight live run needs from the app: a ceiling, and a grader.

Both are about money. A ceiling that cuts off the case in flight wastes the call
it already paid for, and one that lets a second suite start after the budget is
gone is not a ceiling.

How a night is judged — which suites, how the budget is shared between them,
what counts as needing a person in the morning — lives in the map's "Run Nightly
Eval Suites" Server Script, so it can be changed in Processa without a deploy.
It is covered by running the process, not from here.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.agents.eval_ci import run_suite
from one_bpmn.agents.eval_runner import (
	_execute_eval_suite,
	_judge_model_for,
	_run_lane,
)

CASE_EXEC = "one_bpmn.agents.eval_runner._execute_case"


def _priced(cost):
	"""Stand in for a live case, at a known price."""
	def run(case, eval_run=None, agent_cfg=None):
		return {"eval_case": case.name, "status": "Passed", "actual_output": "ok", "cost": cost}
	return run


class TestSpendCeiling(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test ceiling " + frappe.generate_hash(length=6))
		self.cases = [make_eval_case(suite=self.suite.name, expected_output="ok") for _ in range(4)]

	def _run(self, cap):
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": "Running",
			"backend": "live", "scope": "Suite", "spend_cap": cap,
			"started_at": frappe.utils.now_datetime(),
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)
		with patch(CASE_EXEC, side_effect=_priced(1.0)):
			_execute_eval_suite(run.name)
		run.reload()
		return run

	def test_no_ceiling_runs_every_case(self):
		run = self._run(0)
		self.assertEqual(run.passed_cases, 4)
		self.assertFalse((run.stop_reason or "").strip())

	def test_a_ceiling_never_reached_changes_nothing(self):
		run = self._run(100)
		self.assertEqual(run.passed_cases, 4)
		self.assertFalse((run.stop_reason or "").strip())

	def test_it_stops_once_the_ceiling_is_reached(self):
		run = self._run(2.5)
		self.assertEqual(run.passed_cases, 3, "the third case is what crossed the line")
		self.assertIn("Stopped on budget", run.stop_reason)
		self.assertIn("2.5", run.stop_reason)

	def test_the_case_in_flight_is_never_cut_off(self):
		"""Cutting off mid-answer wastes a call that has already been paid for."""
		run = self._run(2.5)
		self.assertEqual(run.results[2].status, "Passed")
		self.assertEqual(run.results[2].actual_output, "ok")

	def test_the_cases_left_over_are_not_run_rather_than_failed(self):
		run = self._run(2.5)
		left = [r for r in run.results if r.status == "Skipped"]
		self.assertEqual(len(left), 1)
		self.assertIn("spend ceiling", left[0].error_message)
		self.assertEqual(run.failed_cases, 0, "running out of money is not a failing suite")

	def test_every_case_is_still_accounted_for(self):
		run = self._run(2.5)
		self.assertEqual(run.total_cases, 4)
		self.assertEqual(len(run.results), 4)


class TestGradingModel(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.model = frappe.get_doc({
			"doctype": "AI Model", "model_name": "_test-grader-" + frappe.generate_hash(length=6),
			"provider": "Anthropic", "model_api_name": "claude-haiku-4-5-20251001",
		})
		self.model.flags.ignore_mandatory = True
		self.model.flags.ignore_links = True
		self.model.insert(ignore_permissions=True)

	def _setting(self, value):
		frappe.db.set_single_value("Processa Settings", "nightly_eval_grading_model", value)

	def test_the_assertion_wins_when_it_names_a_grader(self):
		self._setting(self.model.name)
		model, provider = _judge_model_for(
			frappe._dict(judge_model="its-own-model", judge_provider="OpenAI")
		)
		self.assertEqual((model, provider), ("its-own-model", "OpenAI"))

	def test_the_site_setting_stands_in_when_it_does_not(self):
		self._setting(self.model.name)
		model, provider = _judge_model_for(frappe._dict(judge_model="", judge_provider=""))
		self.assertEqual(model, self.model.name)
		self.assertEqual(provider, "Anthropic", "the provider comes off the model record")

	def test_a_named_model_without_a_provider_gets_one(self):
		self._setting("")
		model, provider = _judge_model_for(
			frappe._dict(judge_model=self.model.name, judge_provider="")
		)
		self.assertEqual((model, provider), (self.model.name, "Anthropic"))

	def test_nothing_configured_anywhere_is_not_a_crash(self):
		"""The judge call itself reports the failure; resolution must not raise."""
		self._setting("")
		self.assertEqual(_judge_model_for(frappe._dict(judge_model="", judge_provider="")), ("", ""))


class TestRunSuiteCarriesTheCeiling(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test carry " + frappe.generate_hash(length=6))
		for _ in range(3):
			make_eval_case(suite=self.suite.name, expected_output="ok")

	def test_the_ceiling_reaches_the_run_and_the_summary_says_it_stopped(self):
		with patch(CASE_EXEC, side_effect=_priced(1.0)):
			summary = run_suite({"name": self.suite.name, "title": self.suite.title}, "live", spend_cap=1.5)

		self.assertEqual(frappe.db.get_value("AI Eval Run", summary["run"], "spend_cap"), 1.5)
		self.assertIn("Stopped on budget", summary["stopped"])
		self.assertEqual(summary["cost"], 2.0)
		self.assertEqual(summary["skipped"], 1)
		self.assertEqual(summary["rate"], 100.0, "the cases that did run all passed")


class TestCeilingAndTheGateTogether(FrappeTestCase):
	"""Where this story meets the deployment gate.

	The gate refuses a deployment on a suite's pass rate. A case that never ran
	— because nothing could be checked without a model, or because the budget
	was gone — must therefore stay out of that rate, or a suite gets blocked for
	having no provider key rather than for behaving badly.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test gate mix " + frappe.generate_hash(length=6))

	def _case(self, answer, assertions):
		case = make_eval_case(suite=self.suite.name, expected_output=answer)
		case.reload()
		case.set("assertions", assertions)
		case.flags.ignore_mandatory = True
		case.save(ignore_permissions=True)
		return case

	def test_a_skipped_case_stays_out_of_the_pass_rate(self):
		self._case("ready", [{"assertion_type": "equals", "value": "ready"}])
		self._case("anything", [{"assertion_type": "llm_judge", "value": "rubric",
								 "judge_provider": "Anthropic", "judge_model": "claude-haiku-4-5-20251001"}])
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": "Running",
			"backend": "deterministic", "scope": "Suite", "started_at": frappe.utils.now_datetime(),
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)
		_execute_eval_suite(run.name)
		run.reload()

		self.assertEqual(run.total_executions, 1, "the skipped case never executed")
		self.assertEqual(run.pass_rate, 100.0, "half of nothing is not a 50% agent")
		self.assertEqual(run.status, "Passed")

	def test_a_deterministic_run_is_not_repeated_k_times(self):
		"""The answer is on the case, so k runs would be k copies of one fact."""
		frappe.db.set_value("AI Eval Suite", self.suite.name, "pass_k", 4)
		self._case("ready", [{"assertion_type": "equals", "value": "ready"}])
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": "Running",
			"backend": "deterministic", "scope": "Suite", "started_at": frappe.utils.now_datetime(),
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)
		_execute_eval_suite(run.name)
		run.reload()
		self.assertEqual(run.total_executions, 1)


class TestCeilingInsideALane(FrappeTestCase):
	"""The ceiling has to survive cases running side by side."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test lane cap " + frappe.generate_hash(length=6))
		self.cases = [make_eval_case(suite=self.suite.name, expected_output="ok") for _ in range(4)]

	def _budget(self, cap):
		import threading
		return {"cap": cap, "spent": 0.0, "not_run": 0, "lock": threading.Lock()}

	def test_a_lane_stops_starting_cases_once_the_budget_is_gone(self):
		budget = self._budget(2.5)
		lane = [c.name for c in self.cases]
		with patch(CASE_EXEC, side_effect=_priced(1.0)):
			rows = _run_lane(lane, "no-run", "live", None, 1, budget)

		ran = [n for n in lane if rows[n]["status"] == "Passed"]
		not_run = [n for n in lane if rows[n]["status"] == "Skipped"]
		self.assertEqual(len(ran), 3, "the third case is what crossed the line")
		self.assertEqual(len(not_run), 1)
		self.assertIn("spend ceiling", rows[not_run[0]]["error_message"])
		self.assertEqual(budget["not_run"], 1)

	def test_a_lane_with_no_ceiling_runs_the_whole_lane(self):
		budget = self._budget(0)
		lane = [c.name for c in self.cases]
		with patch(CASE_EXEC, side_effect=_priced(9.0)):
			rows = _run_lane(lane, "no-run", "live", None, 1, budget)
		self.assertTrue(all(rows[n]["status"] == "Passed" for n in lane))
		self.assertEqual(budget["not_run"], 0)
