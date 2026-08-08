# Copyright (c) 2026, one-fm and contributors
# WI-001821: run one eval suite against two agents and compare the results.
#
# Two halves are tested. The OVERRIDE path: a run may nominate an agent other
# than the suite's, and the suite must come out the other side still bound to
# whatever it was bound to before — a comparison that quietly rebinds the suite
# is worse than no comparison, because the next ordinary run silently tests the
# wrong agent. The GUARD: a comparison must say when it is not apples-to-apples
# instead of printing two numbers side by side as if they meant something.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import (
	make_agent_configuration,
	make_eval_case,
	make_eval_run,
	make_eval_suite,
	patch_executor,
	success_result,
)
from one_bpmn.agents.eval_runner import _execute_eval_suite, run_eval_comparison
from one_bpmn.api.eval_api import get_run_comparison, list_comparable_runs


class TestEvalComparison(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Distinct system prompts: the executor is handed an ExecutorConfig, not
		# the agent doc, so the prompt is the only place the agent's identity is
		# observable from inside the call.
		self.agent_a = make_agent_configuration(system_prompt="I AM AGENT A").name
		self.agent_b = make_agent_configuration(system_prompt="I AM AGENT B").name
		self.suite = make_eval_suite(agent_configuration=self.agent_a)
		self.cases = [
			make_eval_case(
				suite=self.suite.name,
				title=f"_Test case {i}",
				assertions=[{"assertion_type": "contains", "value": "yes"}],
			).name
			for i in range(3)
		]

	# ------------------------------------------------------------------
	# The override path
	# ------------------------------------------------------------------
	def test_a_run_executes_against_its_own_agent_not_the_suites(self):
		run = make_eval_run(self.suite.name, agent_configuration=self.agent_b)
		seen = []

		with patch_executor(lambda config, context: seen.append(config) or success_result("yes")):
			_execute_eval_suite(run.name)

		self.assertEqual(len(seen), 3, "every case should have executed")
		prompts = {c.system_prompt for c in seen}
		self.assertEqual(prompts, {"I AM AGENT B"})

	def test_a_run_without_an_override_still_uses_the_suites_agent(self):
		run = make_eval_run(self.suite.name)
		seen = []

		with patch_executor(lambda config, context: seen.append(config) or success_result("yes")):
			_execute_eval_suite(run.name)

		self.assertEqual({c.system_prompt for c in seen}, {"I AM AGENT A"})
		run.reload()
		self.assertEqual(run.status, "Passed")
		self.assertEqual(len(run.results), 3)

	def test_comparing_never_rebinds_the_suite(self):
		"""The whole point of a run-level override. If this ever fails, every
		ordinary run of the suite afterwards silently tests the wrong agent."""
		res = run_eval_comparison(self.suite.name, agent_b=self.agent_b)

		self.suite.reload()
		self.assertEqual(self.suite.agent_configuration, self.agent_a)
		self.assertNotEqual(res["run_a"], res["run_b"])

	def test_the_pair_shares_a_group_and_records_one_agent_each(self):
		res = run_eval_comparison(self.suite.name, agent_b=self.agent_b)

		a = frappe.get_doc("AI Eval Run", res["run_a"])
		b = frappe.get_doc("AI Eval Run", res["run_b"])
		self.assertEqual(a.comparison_group, b.comparison_group)
		self.assertEqual(a.agent_configuration, self.agent_a)
		self.assertEqual(b.agent_configuration, self.agent_b)

	def test_both_sides_are_frozen_to_the_same_case_list(self):
		"""A case added between the two runs starting must not land on one side
		only — that is a silently unfair comparison."""
		res = run_eval_comparison(self.suite.name, agent_b=self.agent_b)
		make_eval_case(suite=self.suite.name, title="_Test late arrival")

		a = frappe.get_doc("AI Eval Run", res["run_a"])
		b = frappe.get_doc("AI Eval Run", res["run_b"])
		self.assertEqual(frappe.parse_json(a.requested_cases), frappe.parse_json(b.requested_cases))
		self.assertEqual(len(frappe.parse_json(a.requested_cases)), 3)

	def test_comparing_an_agent_against_itself_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			run_eval_comparison(self.suite.name, agent_b=self.agent_a)

	def test_comparing_a_suite_with_no_cases_is_refused(self):
		empty = make_eval_suite(agent_configuration=self.agent_a)
		with self.assertRaises(frappe.ValidationError):
			run_eval_comparison(empty.name, agent_b=self.agent_b)

	def test_an_unknown_agent_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			run_eval_comparison(self.suite.name, agent_b="ZZ no such agent")

	def test_a_subset_comparison_validates_the_cases_belong_to_the_suite(self):
		other = make_eval_case(suite=make_eval_suite().name, title="_Test foreign")
		with self.assertRaises(frappe.ValidationError):
			run_eval_comparison(self.suite.name, agent_b=self.agent_b, case_names=[other.name])

	# ------------------------------------------------------------------
	# The comparison itself
	# ------------------------------------------------------------------
	def _finished(self, agent, statuses, **kwargs):
		"""A finished run of this suite whose per-case statuses are as given."""
		run = make_eval_run(
			self.suite.name,
			agent_configuration=agent,
			status="Failed" if "Failed" in statuses.values() else "Passed",
			**kwargs,
		)
		for case, status in statuses.items():
			run.append("results", {"eval_case": case, "status": status})
		run.total_cases = len(statuses)
		run.passed_cases = sum(1 for s in statuses.values() if s == "Passed")
		run.failed_cases = run.total_cases - run.passed_cases
		run.save(ignore_permissions=True)
		return run

	def test_per_case_outcomes_and_the_tally(self):
		c0, c1, c2 = self.cases
		a = self._finished(self.agent_a, {c0: "Passed", c1: "Failed", c2: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed", c1: "Passed", c2: "Failed"})

		out = get_run_comparison(a.name, b.name)

		outcomes = {c["eval_case"]: c["outcome"] for c in out["cases"]}
		self.assertEqual(outcomes[c0], "tie")
		self.assertEqual(outcomes[c1], "b")
		self.assertEqual(outcomes[c2], "a")
		self.assertEqual(out["tally"], {"a_wins": 1, "b_wins": 1, "ties": 1})

	def test_pass_rate_is_computed_over_the_shared_cases(self):
		c0, c1, c2 = self.cases
		a = self._finished(self.agent_a, {c0: "Passed", c1: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed", c1: "Failed", c2: "Passed"})

		out = get_run_comparison(a.name, b.name)

		# Two shared cases. B's extra pass on c2 must not flatter its rate.
		self.assertEqual(out["a"]["cases_compared"], 2)
		self.assertEqual(out["a"]["pass_rate"], 100.0)
		self.assertEqual(out["b"]["pass_rate"], 50.0)

	def test_neither_passing_is_a_tie_not_a_win(self):
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Failed"})
		b = self._finished(self.agent_b, {c0: "Error"})

		out = get_run_comparison(a.name, b.name)
		self.assertEqual(out["cases"][0]["outcome"], "tie")

	def test_the_pair_resolves_its_other_side_without_being_told(self):
		res = run_eval_comparison(self.suite.name, agent_b=self.agent_b)
		out = get_run_comparison(res["run_a"])
		self.assertEqual(out["b"]["run"], res["run_b"])

	def test_a_lone_run_asked_to_self_resolve_is_refused(self):
		lone = self._finished(self.agent_a, {self.cases[0]: "Passed"})
		with self.assertRaises(frappe.ValidationError):
			get_run_comparison(lone.name)

	# ------------------------------------------------------------------
	# The not-comparable guard
	# ------------------------------------------------------------------
	def _levels(self, out):
		return {n["level"] for n in out["notes"]}

	def test_runs_of_different_suites_are_refused_outright(self):
		other = make_eval_suite(agent_configuration=self.agent_a)
		a = self._finished(self.agent_a, {self.cases[0]: "Passed"})
		b = make_eval_run(other.name, agent_configuration=self.agent_b, status="Passed")

		with self.assertRaises(frappe.ValidationError):
			get_run_comparison(a.name, b.name)

	def test_a_differing_case_set_is_flagged_and_the_overlap_compared(self):
		c0, c1, c2 = self.cases
		a = self._finished(self.agent_a, {c0: "Passed", c1: "Passed"})
		b = self._finished(self.agent_b, {c1: "Passed", c2: "Passed"})

		out = get_run_comparison(a.name, b.name)

		self.assertIn("warning", self._levels(out))
		self.assertEqual([c["eval_case"] for c in out["cases"]], [c1])
		self.assertEqual(out["only_in_a"], [c0])
		self.assertEqual(out["only_in_b"], [c2])
		self.assertFalse(out["blocked"])

	def test_no_shared_cases_blocks_the_comparison(self):
		c0, c1 = self.cases[0], self.cases[1]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c1: "Passed"})

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(out["blocked"])
		self.assertIn("blocking", self._levels(out))

	def test_a_running_pair_is_not_told_it_shares_no_cases(self):
		"""A queued run has no result rows yet, so the shared-case set is
		trivially empty. Reporting that alongside "still running" reads as a
		structural incompatibility rather than as "not finished yet"."""
		a = make_eval_run(self.suite.name, agent_configuration=self.agent_a, status="Running")
		b = make_eval_run(self.suite.name, agent_configuration=self.agent_b, status="Running")

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(out["blocked"], "a running pair still has nothing to show")
		self.assertFalse(
			any("share no cases" in n["message"] for n in out["notes"]),
			out["notes"],
		)
		self.assertTrue(any(n["level"] == "pending" for n in out["notes"]), out["notes"])

	def test_an_errored_run_with_no_results_does_report_no_shared_cases(self):
		"""The suppression above is scoped to RUNNING. A finished run that
		produced nothing genuinely has nothing to compare, and saying so is the
		only signal the user gets."""
		a = self._finished(self.agent_a, {self.cases[0]: "Passed"})
		b = make_eval_run(self.suite.name, agent_configuration=self.agent_b, status="Error")

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(any("share no cases" in n["message"] for n in out["notes"]), out["notes"])

	def test_a_running_run_is_pending_not_a_refusal(self):
		"""'Can't compare' must mean the user has something to fix. A run that is
		simply still going resolves itself, so it must not wear the same label."""
		a = self._finished(self.agent_a, {self.cases[0]: "Passed"})
		b = make_eval_run(self.suite.name, agent_configuration=self.agent_b, status="Running")

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(out["pending"])
		self.assertTrue(out["blocked"], "there is still nothing to show")
		self.assertFalse(
			any(n["level"] == "blocking" for n in out["notes"]),
			"a run in flight is not a refusal: " + str(out["notes"]),
		)

	def test_a_real_refusal_is_not_marked_pending(self):
		c0, c1 = self.cases[0], self.cases[1]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c1: "Passed"})

		out = get_run_comparison(a.name, b.name)

		self.assertFalse(out["pending"])
		self.assertTrue(out["blocked"])
		self.assertTrue(any(n["level"] == "blocking" for n in out["notes"]))

	def test_a_still_running_run_blocks_the_comparison(self):
		a = self._finished(self.agent_a, {self.cases[0]: "Passed"})
		b = make_eval_run(self.suite.name, agent_configuration=self.agent_b, status="Running")
		b.append("results", {"eval_case": self.cases[0], "status": "Passed"})
		b.save(ignore_permissions=True)

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(out["blocked"])

	def test_an_errored_run_is_flagged_but_still_compared(self):
		"""Partial evidence beats no evidence — show the cases that finished."""
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Failed"})
		b.db_set("status", "Error")

		out = get_run_comparison(a.name, b.name)

		self.assertFalse(out["blocked"])
		self.assertIn("warning", self._levels(out))
		self.assertEqual(len(out["cases"]), 1)

	def test_the_same_agent_on_both_sides_is_flagged(self):
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_a, {c0: "Failed"})

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(
			any("same agent" in n["message"].lower() for n in out["notes"]),
			out["notes"],
		)

	def test_a_run_with_no_recorded_agent_is_flagged(self):
		"""Runs predating WI-001821 don't say what they tested."""
		c0 = self.cases[0]
		a = self._finished(None, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed"})

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(
			any("does not record which agent" in n["message"] for n in out["notes"]),
			out["notes"],
		)

	def test_mixing_live_and_replay_is_flagged(self):
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed"}, backend="replay")

		out = get_run_comparison(a.name, b.name)

		self.assertTrue(any("replay" in n["message"].lower() for n in out["notes"]), out["notes"])

	def test_a_small_sample_is_surfaced_not_hidden(self):
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Failed"})

		out = get_run_comparison(a.name, b.name)

		self.assertIn("caution", self._levels(out))
		self.assertFalse(out["blocked"], "a small sample is a caveat, not a refusal")

	# ------------------------------------------------------------------
	# Latency and the cost split
	# ------------------------------------------------------------------
	def _agent_run(self, run, agent, **kwargs):
		"""An eval-origin AI Agent Run, the record the comparison reads latency
		and the cost split from."""
		doc = {
			"doctype": "AI Agent Run",
			"origin": "eval",
			"eval_run": run.name,
			"agent_configuration": agent,
			"bpmn_id": "_test_task",
			"started_at": frappe.utils.now_datetime(),
			"status": "Success",
		}
		doc.update(kwargs)
		return frappe.get_doc(doc).insert(ignore_permissions=True)

	def test_latency_and_the_cache_cost_split_are_aggregated_per_agent(self):
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed"})
		for run, agent, latency, cache_read in (
			(a, self.agent_a, 400, 0.01),
			(a, self.agent_a, 600, 0.01),
			(b, self.agent_b, 1000, 0.05),
		):
			self._agent_run(
				run, agent, eval_case=c0, agent_latency_ms=latency,
				total_input_cost=0.02, total_output_cost=0.03,
				total_cache_read_cost=cache_read, total_cache_write_cost=0.004,
				estimated_cost=0.064,
			)

		out = get_run_comparison(a.name, b.name)

		self.assertEqual(out["a"]["mean_latency_ms"], 500)
		self.assertEqual(out["b"]["mean_latency_ms"], 1000)
		self.assertAlmostEqual(out["a"]["cost_split"]["cache_read"], 0.02)
		self.assertAlmostEqual(out["b"]["cost_split"]["cache_read"], 0.05)
		self.assertAlmostEqual(out["a"]["cost_split"]["input"], 0.04)

	def test_judge_calls_are_kept_out_of_the_agents_latency_and_cost(self):
		"""The judge is the examiner, not the subject. Averaging its round-trips
		into "mean agent latency" measures the wrong model, and folding its spend
		into the agent's split makes a cheap agent look expensive because an
		expensive judge marked it."""
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed"})
		self._agent_run(a, self.agent_a, agent_latency_ms=500,
		                total_input_cost=0.001, estimated_cost=0.001)
		# A judge call: no agent_configuration, slow and expensive.
		self._agent_run(a, None, agent_latency_ms=9000, estimated_cost=0.75)

		out = get_run_comparison(a.name, b.name)

		self.assertEqual(out["a"]["mean_latency_ms"], 500)
		self.assertEqual(out["a"]["agent_calls"], 1)
		self.assertAlmostEqual(out["a"]["cost_split"]["input"], 0.001)
		self.assertAlmostEqual(out["a"]["judge_cost"], 0.75)

	def test_unmeasured_latency_does_not_drag_the_mean_to_zero(self):
		c0 = self.cases[0]
		a = self._finished(self.agent_a, {c0: "Passed"})
		b = self._finished(self.agent_b, {c0: "Passed"})
		for latency in (800, 0):
			self._agent_run(a, self.agent_a, agent_latency_ms=latency)

		out = get_run_comparison(a.name, b.name)

		self.assertEqual(out["a"]["mean_latency_ms"], 800)
		self.assertEqual(out["a"]["latency_samples"], 1)
		# Nothing measured at all reads as unknown, not as zero.
		self.assertIsNone(out["b"]["mean_latency_ms"])

	# ------------------------------------------------------------------
	# The picker
	# ------------------------------------------------------------------
	def test_comparable_runs_exclude_self_and_flag_same_agent(self):
		c0 = self.cases[0]
		mine = self._finished(self.agent_a, {c0: "Passed"})
		same = self._finished(self.agent_a, {c0: "Passed"})
		other = self._finished(self.agent_b, {c0: "Passed"})

		names = {r["name"]: r for r in list_comparable_runs(mine.name)}

		self.assertNotIn(mine.name, names)
		self.assertTrue(names[same.name]["same_agent"])
		self.assertFalse(names[other.name]["same_agent"])
