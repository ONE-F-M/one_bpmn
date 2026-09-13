# Copyright (c) 2026, one-fm and contributors
"""Sampling real traffic, and scoring what comes back.

The scoring is the easy half — it is the same assertion machinery the suites
use. The sampling is where this can quietly fail: a flat sample of this site's
traffic is almost all runs that went fine, so a measure built on it would look
healthy while the failures went unread. Most of these tests are about the bias
being real, and about it still being a sample rather than a worst-N list.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration, make_eval_suite
from one_bpmn.agents.online_eval import (
	DEFAULT_WEIGHTS,
	candidates,
	draw,
	rubric_assertions,
	rubric_suite,
	score,
	sweep,
	weigh,
)


def _run(agent, **kwargs):
	values = {
		"doctype": "AI Agent Run",
		"agent_configuration": agent,
		"origin": "production",
		"status": "Success",
		"final_output": "the agent said something",
		"started_at": frappe.utils.now_datetime(),
	}
	values.update(kwargs)
	doc = frappe.get_doc(values)
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


class TestWeighting(FrappeTestCase):
	"""Which runs the draw leans toward, and why it says so."""

	def test_ordinary_traffic_carries_the_base_weight(self):
		weight, reason = weigh({})
		self.assertEqual(weight, DEFAULT_WEIGHTS["base"])
		self.assertEqual(reason, "ordinary traffic")

	def test_an_abandoned_run_outweighs_an_ordinary_one(self):
		self.assertGreater(weigh({"is_abandoned": True})[0], weigh({})[0])

	def test_a_corrected_run_outweighs_an_ordinary_one(self):
		self.assertGreater(weigh({"is_corrected": True})[0], weigh({})[0])

	def test_signals_compound(self):
		"""Expensive AND abandoned is the combination most worth reading."""
		both = weigh({"is_abandoned": True, "is_expensive": True})[0]
		self.assertGreater(both, weigh({"is_abandoned": True})[0])
		self.assertGreater(both, weigh({"is_expensive": True})[0])

	def test_the_reason_names_every_signal(self):
		_, reason = weigh({"is_abandoned": True, "is_corrected": True})
		self.assertIn("abandoned", reason)
		self.assertIn("corrected", reason)


class TestDraw(FrappeTestCase):
	def _pool(self):
		pool = [{"name": f"ordinary-{i}"} for i in range(40)]
		pool.append({"name": "abandoned-1", "is_abandoned": True})
		pool.append({"name": "corrected-1", "is_corrected": True})
		return pool

	def test_it_leans_hard_toward_the_informative_runs(self):
		"""The point of the story: a flat sample would meet these twice a year."""
		hits = 0
		for seed in range(40):
			picked = {r["name"] for r in draw(self._pool(), 5, seed=seed)}
			if picked & {"abandoned-1", "corrected-1"}:
				hits += 1
		self.assertGreater(hits, 20, f"informative runs appeared in only {hits}/40 draws")

	def test_it_is_still_a_sample_not_a_worst_first_list(self):
		"""Ordinary runs must keep appearing, or the middle drifting is never seen."""
		ordinary = 0
		for seed in range(20):
			for r in draw(self._pool(), 5, seed=seed):
				if r["name"].startswith("ordinary"):
					ordinary += 1
		self.assertGreater(ordinary, 20, "the draw never looked at ordinary traffic")

	def test_no_run_is_drawn_twice(self):
		picked = [r["name"] for r in draw(self._pool(), 10, seed=1)]
		self.assertEqual(len(picked), len(set(picked)))

	def test_asking_for_more_than_exists_returns_what_exists(self):
		self.assertEqual(len(draw([{"name": "a"}, {"name": "b"}], 10)), 2)

	def test_every_pick_carries_the_reason_it_was_picked(self):
		for r in draw(self._pool(), 6, seed=3):
			self.assertTrue(r["sample_reason"])

	def test_an_empty_window_draws_nothing(self):
		self.assertEqual(draw([], 5), [])


class TestCandidates(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.agent = make_agent_configuration().name

	def test_eval_traffic_is_not_production_traffic(self):
		"""Scoring our own eval runs would be marking our own homework."""
		_run(self.agent, origin="eval")
		self.assertEqual(candidates(self.agent), [])

	def test_a_run_still_going_is_not_a_candidate(self):
		_run(self.agent, status="Running")
		self.assertEqual(candidates(self.agent), [])

	def test_a_run_that_said_nothing_is_not_a_candidate(self):
		"""There is no answer to score."""
		_run(self.agent, final_output="")
		self.assertEqual(candidates(self.agent), [])

	def test_a_failed_run_is_a_candidate(self):
		_run(self.agent, status="Error", final_output="it broke")
		self.assertEqual(len(candidates(self.agent)), 1)

	def test_the_signals_are_read_off_the_run(self):
		_run(self.agent, goal_completion="Not Achieved", retry_count=2)
		row = candidates(self.agent)[0]
		self.assertTrue(row["is_abandoned"])
		self.assertTrue(row["is_retried"])

	def test_a_person_saying_it_was_wrong_marks_the_run(self):
		run = _run(self.agent)
		message = frappe.get_doc({"doctype": "Chat Message", "text": "the reply",
								  "message_type": "Bot"})
		message.flags.ignore_mandatory = True
		message.flags.ignore_links = True
		message.insert(ignore_permissions=True)
		fb = frappe.get_doc({"doctype": "AI Response Feedback", "rating": "Negative",
							 "agent_run": run.name, "agent_configuration": self.agent,
							 "message": message.name, "rated_by": frappe.session.user,
							 "rated_on": frappe.utils.now_datetime(),
							 "comment": "it invented a reference number"})
		fb.flags.ignore_mandatory = True
		fb.flags.ignore_links = True
		fb.insert(ignore_permissions=True)
		self.assertTrue(candidates(self.agent)[0]["is_corrected"])

    # a cost threshold in currency goes stale the moment models change
	def test_expensive_is_relative_to_the_window(self):
		for cost in [0.001] * 12:
			_run(self.agent, estimated_cost=cost)
		_run(self.agent, estimated_cost=5.0)
		rows = candidates(self.agent)
		dear = [r for r in rows if r["is_expensive"]]
		self.assertEqual(len(dear), 1)
		self.assertEqual(dear[0]["estimated_cost"], 5.0)


class TestScoringAndSweep(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.agent = make_agent_configuration().name
		self.suite = make_eval_suite(process_model=None, agent_configuration=self.agent,
									 title="_Test rubric " + frappe.generate_hash(length=6),
									 suite_type="Online Rubric")
		case = frappe.get_doc({"doctype": "AI Eval Case", "suite": self.suite.name,
							   "title": "Rubric", "input_user_prompt": "n/a",
							   "assertions": [{"assertion_type": "contains", "value": "disabled"}]})
		case.flags.ignore_mandatory = True
		case.insert(ignore_permissions=True)

	def test_the_rubric_is_found_by_its_suite_type(self):
		self.assertEqual(rubric_suite(self.agent), self.suite.name)
		self.assertEqual(len(rubric_assertions(self.suite.name)), 1)

	def test_an_answer_meeting_the_rubric_passes(self):
		row = score({"name": "r1", "final_output": "left it disabled"},
					rubric_assertions(self.suite.name))
		self.assertEqual(row["status"], "Passed")
		self.assertEqual(row["source_run"], "r1")

	def test_an_answer_failing_the_rubric_says_which_standard(self):
		row = score({"name": "r1", "final_output": "all switched on"},
					rubric_assertions(self.suite.name))
		self.assertEqual(row["status"], "Failed")
		self.assertIn("contains", row["error_message"])

	def test_a_sweep_records_a_run_anyone_can_read(self):
		_run(self.agent, final_output="left it disabled")
		out = sweep(self.agent, size=5)
		self.assertEqual(out["scored"], 1)
		doc = frappe.get_doc("AI Eval Run", out["run"])
		self.assertEqual(doc.scope, "Online")
		self.assertEqual(doc.results[0].source_run, frappe.get_all("AI Agent Run",
			filters={"agent_configuration": self.agent}, pluck="name")[0])
		self.assertFalse(doc.results[0].eval_case, "an online sample has no case")

	def test_the_result_records_why_the_run_was_sampled(self):
		_run(self.agent, goal_completion="Not Achieved", final_output="left it disabled")
		doc = frappe.get_doc("AI Eval Run", sweep(self.agent, size=5)["run"])
		self.assertIn("abandoned", doc.results[0].sample_reason)

	def test_an_agent_with_no_rubric_is_reported_not_scored(self):
		other = make_agent_configuration().name
		out = sweep(other)
		self.assertEqual(out["scored"], 0)
		self.assertIn("no Online Rubric", out["problem"])

	def test_a_rubric_with_no_assertions_is_reported(self):
		bare = make_agent_configuration().name
		make_eval_suite(process_model=None, agent_configuration=bare, suite_type="Online Rubric",
						title="_Test bare rubric " + frappe.generate_hash(length=6))
		self.assertIn("no assertions", sweep(bare)["problem"])

	def test_a_quiet_window_is_reported_not_an_error(self):
		self.assertIn("No finished production run", sweep(self.agent, window_hours=1)["problem"])
