# Copyright (c) 2026, one-fm and contributors
"""The overnight live run: its ceiling, its grader, and what it reports.

Two of these are about money. A ceiling that cuts off the case in flight wastes
the call it already paid for, and a ceiling that lets a second suite start after
the budget is gone is not a ceiling. The rest are about the report an alert is
built from: "we ran out of budget" and "the agent got worse" must never arrive
looking the same.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.agents.eval_ci import run_suite
from one_bpmn.agents.eval_nightly import run_nightly
from one_bpmn.agents.eval_runner import _execute_eval_suite, _judge_model_for

CASE_EXEC = "one_bpmn.agents.eval_runner._execute_case"
SELECT = "one_bpmn.agents.eval_nightly.select_suites"
RUN_SUITE = "one_bpmn.agents.eval_nightly.run_suite"


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


def _summary(suite, rate=100.0, cost=0.0, stopped="", failures=None):
	return {"suite": suite, "run": "r-" + suite, "status": "Passed", "cases": 2, "checked": 2,
			"passed": 2, "skipped": 0, "rate": rate, "cost": cost, "stopped": stopped,
			"failures": failures or []}


class TestNightlySelection(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.tagged = make_eval_suite(title="_Test nightly A " + frappe.generate_hash(length=6), ci_role="Nightly")
		self.smoke = make_eval_suite(title="_Test smoke A " + frappe.generate_hash(length=6), ci_role="Smoke")
		self.untagged = make_eval_suite(title="_Test plain A " + frappe.generate_hash(length=6))

	def test_it_runs_the_nightly_ones_and_leaves_the_others_alone(self):
		seen = []

		def stub(suite, backend, spend_cap=0):
			seen.append(suite["name"])
			return _summary(suite["title"])

		with patch(RUN_SUITE, side_effect=stub):
			run_nightly()

		self.assertIn(self.tagged.name, seen)
		self.assertNotIn(self.smoke.name, seen)
		self.assertNotIn(self.untagged.name, seen)


class TestNightlyReport(FrappeTestCase):
	"""What an alert would be built from."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.two = [{"name": "s1", "title": "First", "ci_role": "Nightly"},
					{"name": "s2", "title": "Second", "ci_role": "Nightly"}]

	def test_nothing_tagged_is_not_a_failure(self):
		with patch(SELECT, return_value=[]):
			out = run_nightly()
		self.assertTrue(out["ok"])
		self.assertIn("No eval suite is tagged Nightly", out["summary_line"])

	def test_a_suite_below_the_bar_is_named_with_its_rate(self):
		with patch(SELECT, return_value=self.two), \
			 patch(RUN_SUITE, side_effect=[_summary("First", rate=100.0), _summary("Second", rate=62.5)]):
			out = run_nightly(min_pass=90)
		self.assertFalse(out["ok"])
		self.assertEqual([b["suite"] for b in out["below_minimum"]], ["Second"])
		self.assertIn("Second at 62.5%", out["summary_line"])

	def test_a_suite_that_checked_nothing_is_reported_separately(self):
		with patch(SELECT, return_value=self.two[:1]), \
			 patch(RUN_SUITE, side_effect=[_summary("First", rate=None)]):
			out = run_nightly()
		self.assertEqual(out["checked_nothing"], ["First"])
		self.assertFalse(out["ok"])

	def test_all_above_the_bar_says_so(self):
		with patch(SELECT, return_value=self.two), \
			 patch(RUN_SUITE, side_effect=[_summary("First"), _summary("Second")]):
			out = run_nightly(min_pass=90)
		self.assertTrue(out["ok"])
		self.assertIn("all above the bar", out["summary_line"])

	def test_the_ceiling_is_shared_across_the_night_not_given_to_each_suite(self):
		frappe.db.set_single_value("Processa Settings", "nightly_eval_spend_cap", 3)
		given = []

		def stub(suite, backend, spend_cap=0):
			given.append(spend_cap)
			return _summary(suite["title"], cost=1.25)

		with patch(SELECT, return_value=self.two), patch(RUN_SUITE, side_effect=stub):
			out = run_nightly()

		self.assertEqual(given[0], 3)
		self.assertEqual(given[1], 1.75, "the second suite gets what the first left")
		self.assertEqual(out["spent"], 2.5)

	def test_a_suite_is_not_started_once_the_budget_is_gone(self):
		frappe.db.set_single_value("Processa Settings", "nightly_eval_spend_cap", 2)
		started = []

		def stub(suite, backend, spend_cap=0):
			started.append(suite["title"])
			return _summary(suite["title"], cost=2.0)

		with patch(SELECT, return_value=self.two), patch(RUN_SUITE, side_effect=stub):
			out = run_nightly()

		self.assertEqual(started, ["First"])
		self.assertEqual(out["suites_not_run"], ["Second"])
		self.assertFalse(out["ok"], "a night that could not finish is not a clean night")
		self.assertIn("1 not run on budget", out["summary_line"])

	def test_running_out_of_budget_does_not_read_as_the_agents_getting_worse(self):
		with patch(SELECT, return_value=self.two[:1]), \
			 patch(RUN_SUITE, side_effect=[_summary("First", stopped="Stopped on budget: spent 2 of 2.")]):
			out = run_nightly()
		self.assertEqual(out["stopped_on_budget"], ["First"])
		self.assertEqual(out["below_minimum"], [], "its rate was fine as far as it got")

	def test_no_ceiling_means_no_ceiling(self):
		frappe.db.set_single_value("Processa Settings", "nightly_eval_spend_cap", 0)
		given = []

		def stub(suite, backend, spend_cap=0):
			given.append(spend_cap)
			return _summary(suite["title"], cost=99.0)

		with patch(SELECT, return_value=self.two), patch(RUN_SUITE, side_effect=stub):
			run_nightly()
		self.assertEqual(given, [0, 0])


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
