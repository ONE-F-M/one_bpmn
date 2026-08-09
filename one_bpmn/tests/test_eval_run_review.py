# Copyright (c) 2026, one-fm and contributors
# WI-001747: the run-review comparison baseline.
#
# Once WI-001746 allowed running a SUBSET of a suite's cases, "the immediately
# previous run" stopped being a usable baseline: consecutive runs routinely share
# no cases at all, so every case reported no delta even when it had plenty of
# history. The baseline is therefore resolved per case — the most recent earlier
# run that actually covered that case — and can be pinned to one chosen run.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.api.eval_api import get_run_review

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]


def _run_with_results(suite: str, case_statuses: dict, minutes_ago: int):
	"""A finished run covering exactly ``case_statuses`` ({case: status}).

	``creation`` is forced to a distinct point in the past: the baseline logic
	orders by creation, and rows inserted in the same test would otherwise share
	a timestamp and order arbitrarily.
	"""
	statuses = list(case_statuses.values())
	run = frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite,
		"status": "Failed" if "Failed" in statuses else "Passed",
		"backend": "live",
		"started_at": now_datetime(),
		"total_cases": len(case_statuses),
		"passed_cases": statuses.count("Passed"),
		"failed_cases": statuses.count("Failed"),
		"results": [
			{"eval_case": case, "status": status, "actual_output": "out"}
			for case, status in case_statuses.items()
		],
	})
	run.flags.ignore_links = True
	run.insert(ignore_permissions=True)
	stamp = add_to_date(now_datetime(), minutes=-minutes_ago)
	frappe.db.set_value("AI Eval Run", run.name, "creation", stamp, update_modified=False)
	return run.name


def _agent_run(eval_run: str, eval_case: str, bpmn_id: str = "ai_agent_task", steps=None):
	"""An eval-origin AI Agent Run with optional steps and tool calls.

	``steps`` is a list of (role, [tool_name, ...]) so a test can describe the
	shape it cares about without spelling out child rows.
	"""
	run = frappe.get_doc({
		"doctype": "AI Agent Run",
		"bpmn_id": bpmn_id,
		"element_type": "task",
		"origin": "eval",
		"status": "Success",
		"eval_case": eval_case,
		"eval_run": eval_run,
		"total_tokens": 100,
		"estimated_cost": 0.25,
	})
	run.flags.ignore_mandatory = True
	run.flags.ignore_links = True
	run.insert(ignore_permissions=True)

	for idx, (role, tools) in enumerate(steps or []):
		step = frappe.get_doc({
			"doctype": "AI Agent Step",
			"run": run.name,
			"step_index": idx,
			"role": role,
			"content": f"{role} content",
			"cost": 0,
			"tool_calls": [
				{
					"tool_name": t,
					"tool_source": "diagram_task",
					"status": "Success",
					"tool_args": '{"a": 1}',
					"tool_result": '{"ok": true}',
				}
				for t in tools
			],
		})
		step.flags.ignore_mandatory = True
		step.insert(ignore_permissions=True)
	return run.name


class TestRunReviewTranscript(FrappeTestCase):
	"""The review payload carries what the agent DID, not just what it answered.

	Before this, "which tools did the eval call?" could only be answered by
	filtering AI Agent Run on origin="eval", matching the run's time window, then
	opening each AI Agent Step to read its tool_calls table.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite().name
		self.case_a = make_eval_case(suite=self.suite).name
		self.case_b = make_eval_case(suite=self.suite).name

	def _review(self, statuses):
		run = _run_with_results(self.suite, statuses, minutes_ago=1)
		return run, get_run_review(run)

	def test_tool_calls_are_grouped_under_their_case(self):
		run, _ = self._review({self.case_a: "Passed", self.case_b: "Passed"})
		_agent_run(run, self.case_a, steps=[
			("system", []), ("user", []),
			("tool", ["get_leave_application"]),
			("tool", ["calculate_leave_duration"]),
			("assistant", []),
		])
		_agent_run(run, self.case_b, steps=[("assistant", [])])

		review = get_run_review(run)
		by_case = {r["eval_case"]: r for r in review["results"]}

		a = by_case[self.case_a]["agent_runs"]
		self.assertEqual(len(a), 1)
		self.assertEqual(a[0]["tool_call_count"], 2)
		self.assertEqual(len(a[0]["steps"]), 5)
		names = [tc["tool_name"] for s in a[0]["steps"] for tc in s["tool_calls"]]
		self.assertEqual(names, ["get_leave_application", "calculate_leave_duration"])
		# Arguments and results travel with the call — the whole point.
		call = next(tc for s in a[0]["steps"] for tc in s["tool_calls"])
		self.assertEqual(call["tool_args"], '{"a": 1}')
		self.assertEqual(call["tool_result"], '{"ok": true}')
		self.assertEqual(call["tool_source"], "diagram_task")

		b = by_case[self.case_b]["agent_runs"]
		self.assertEqual(len(b), 1)
		self.assertEqual(b[0]["tool_call_count"], 0)

	def test_judge_runs_are_excluded(self):
		"""A judge call is the assertion's own LLM call, already reported per
		assertion, and has no steps — it must not appear as agent activity."""
		run, _ = self._review({self.case_a: "Passed"})
		_agent_run(run, self.case_a, bpmn_id="eval-judge")
		_agent_run(run, self.case_a, bpmn_id="ai_agent_task", steps=[("assistant", [])])

		review = get_run_review(run)
		runs = review["results"][0]["agent_runs"]
		self.assertEqual([r["bpmn_id"] for r in runs], ["ai_agent_task"])

	def test_no_agent_runs_yields_an_empty_list(self):
		"""A Direct eval records no step-bearing run; the key must still exist so
		the view can branch on it without null checks."""
		run, review = self._review({self.case_a: "Passed"})
		self.assertEqual(review["results"][0]["agent_runs"], [])

	def test_runs_from_another_eval_run_are_not_included(self):
		run_one, _ = self._review({self.case_a: "Passed"})
		run_two = _run_with_results(self.suite, {self.case_a: "Passed"}, minutes_ago=2)
		_agent_run(run_two, self.case_a, steps=[("tool", ["other_tool"])])

		review = get_run_review(run_one)
		self.assertEqual(review["results"][0]["agent_runs"], [])


class TestEvalRunReviewBaseline(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite().name
		self.case_a = make_eval_case(suite=self.suite).name
		self.case_b = make_eval_case(suite=self.suite).name
		self.case_c = make_eval_case(suite=self.suite).name

	def test_baseline_skips_a_previous_run_that_shared_no_cases(self):
		"""The reported bug: run N-1 covered a different case, so the review
		showed no comparison at all even though both cases had history."""
		_run_with_results(self.suite, {self.case_a: "Failed", self.case_b: "Passed"}, 40)
		# The immediately previous run — a subset covering only case_c.
		_run_with_results(self.suite, {self.case_c: "Passed"}, 20)
		current = _run_with_results(self.suite, {self.case_a: "Failed", self.case_b: "Passed"}, 5)

		review = get_run_review(current)
		baselines = review["case_baselines"]

		# Both cases resolve, despite the previous run covering neither.
		self.assertEqual(baselines[self.case_a]["status"], "Failed")
		self.assertEqual(baselines[self.case_b]["status"], "Passed")

	def test_baseline_is_the_most_recent_run_covering_each_case(self):
		oldest = _run_with_results(self.suite, {self.case_a: "Passed"}, 60)
		newer = _run_with_results(self.suite, {self.case_a: "Failed"}, 30)
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)

		baseline = get_run_review(current)["case_baselines"][self.case_a]
		self.assertEqual(baseline["run"], newer)
		self.assertNotEqual(baseline["run"], oldest)
		# Passed now, Failed then — the improvement the UI badges.
		self.assertEqual(baseline["status"], "Failed")

	def test_each_case_may_resolve_to_a_different_run(self):
		run_a = _run_with_results(self.suite, {self.case_a: "Failed"}, 50)
		run_b = _run_with_results(self.suite, {self.case_b: "Passed"}, 40)
		current = _run_with_results(self.suite, {self.case_a: "Passed", self.case_b: "Passed"}, 5)

		baselines = get_run_review(current)["case_baselines"]
		self.assertEqual(baselines[self.case_a]["run"], run_a)
		self.assertEqual(baselines[self.case_b]["run"], run_b)

	def test_pinned_baseline_compares_against_only_that_run(self):
		oldest = _run_with_results(self.suite, {self.case_a: "Passed"}, 60)
		_run_with_results(self.suite, {self.case_a: "Failed"}, 30)
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)

		review = get_run_review(current, baseline=oldest)
		self.assertEqual(review["baseline"], oldest)
		self.assertEqual(review["case_baselines"][self.case_a]["run"], oldest)
		self.assertEqual(review["case_baselines"][self.case_a]["status"], "Passed")

	def test_case_missing_from_pinned_baseline_has_no_entry(self):
		"""So the UI can say "not in baseline run" rather than silently showing
		nothing — the ambiguity that made the bug invisible."""
		other = _run_with_results(self.suite, {self.case_c: "Passed"}, 30)
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)

		review = get_run_review(current, baseline=other)
		self.assertNotIn(self.case_a, review["case_baselines"])

	def test_first_ever_run_has_no_baseline(self):
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)
		review = get_run_review(current)
		self.assertEqual(review["case_baselines"], {})
		self.assertEqual(review["baselines"], [])
		self.assertIsNone(review["previous"])

	def test_baselines_are_newest_first_and_exclude_this_run(self):
		older = _run_with_results(self.suite, {self.case_a: "Passed"}, 60)
		newer = _run_with_results(self.suite, {self.case_a: "Failed"}, 30)
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)

		names = [b["name"] for b in get_run_review(current)["baselines"]]
		self.assertEqual(names, [newer, older])
		self.assertNotIn(current, names)

	def test_unknown_baseline_is_rejected(self):
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)
		with self.assertRaises(frappe.ValidationError):
			get_run_review(current, baseline="does-not-exist")

	def test_baseline_from_another_suite_is_rejected(self):
		"""A run name is not enough — it must belong to this suite."""
		foreign = _run_with_results(make_eval_suite().name, {self.case_a: "Passed"}, 30)
		current = _run_with_results(self.suite, {self.case_a: "Passed"}, 5)
		with self.assertRaises(frappe.ValidationError):
			get_run_review(current, baseline=foreign)
