# Memory quality as numbers: how much of what the distiller produced was worth
# keeping, how much of what mattered comes back on a question, and whether
# recall fits in the time the dispatch path can give it.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import evals as E
from one_bpmn.agents.memory import tools as T

GOLDEN = [
	"Invoices are approved by the finance lead.",
	"Export orders ship by DHL.",
]


def _words_only():
	"""Force the word-overlap comparison, so a test asserting exact numbers does
	not depend on a model being installed or on its similarity scores."""
	return patch.object(E, "_similarities", side_effect=lambda p, g: [[E._word_overlap(x, y) for y in g] for x in p])


class TestGenerationScoring(FrappeTestCase):
	def test_a_perfect_distillation_scores_one(self):
		with _words_only():
			score = E.score_generation(list(GOLDEN), GOLDEN)
		self.assertEqual((score["precision"], score["recall"], score["f1"]), (1.0, 1.0, 1.0))

	def test_a_missed_fact_costs_recall_but_not_precision(self):
		with _words_only():
			score = E.score_generation([GOLDEN[0]], GOLDEN)
		self.assertEqual(score["precision"], 1.0)
		self.assertEqual(score["recall"], 0.5)
		self.assertEqual(score["f1"], 0.667)

	def test_an_invented_fact_costs_precision_but_not_recall(self):
		with _words_only():
			score = E.score_generation([*GOLDEN, "The cat sat on the mat."], GOLDEN)
		self.assertEqual(score["precision"], 0.667)
		self.assertEqual(score["recall"], 1.0)

	def test_saying_the_same_thing_five_ways_does_not_score_five(self):
		with _words_only():
			score = E.score_generation([GOLDEN[0]] * 5, GOLDEN)
		self.assertEqual(score["matched"], 1)
		self.assertEqual(score["precision"], 0.2)

	def test_keeping_nothing_when_there_was_nothing_is_a_pass(self):
		"""The commonest right answer the distiller gives, and it must not read
		as a division by zero or a failure."""
		score = E.score_generation([], [])
		self.assertEqual(score["f1"], 1.0)

	def test_keeping_nothing_when_something_mattered_is_not(self):
		with _words_only():
			score = E.score_generation([], GOLDEN)
		self.assertEqual((score["recall"], score["f1"]), (0.0, 0.0))

	def test_the_same_fact_in_different_words_still_counts(self):
		"""The distiller rewrites a fact in its own words, so comparing strings
		would score a correct memory as a miss."""
		from one_bpmn.agents.llm_provider import embedding

		if embedding.embed(["probe"]) is None:
			self.skipTest("embedding model unavailable")
		score = E.score_generation(["The finance lead signs off on invoices."], [GOLDEN[0]])
		self.assertEqual(score["recall"], 1.0)


class TestRetrievalScoring(FrappeTestCase):
	def test_everything_expected_came_back(self):
		with _words_only():
			score = E.score_retrieval(GOLDEN, GOLDEN, k=5)
		self.assertEqual(score["recall_at_k"], 1.0)

	def test_only_the_top_k_are_counted(self):
		"""Ordering is the point: a memory ranked eleventh was not recalled."""
		with _words_only():
			score = E.score_retrieval(["noise", *GOLDEN], GOLDEN, k=1)
		self.assertEqual(score["recall_at_k"], 0.0)
		self.assertEqual(score["returned"], 1)

	def test_expecting_nothing_is_a_pass(self):
		self.assertEqual(E.score_retrieval([], [], k=5)["recall_at_k"], 1.0)


class TestLatency(FrappeTestCase):
	def test_a_call_is_timed_and_its_result_returned(self):
		result, ms = E.timed(lambda: "answer")
		self.assertEqual(result, "answer")
		self.assertGreaterEqual(ms, 0)

	def test_the_budget_is_the_dispatch_path_budget(self):
		self.assertEqual(E.RETRIEVAL_BUDGET_MS, 200)
		self.assertTrue(E.within_budget(199.0))
		self.assertFalse(E.within_budget(200.1))


class TestOneCaseEndToEnd(FrappeTestCase):
	def setUp(self):
		self.agent = f"EV_{frappe.generate_hash(length=8)}"
		for content in GOLDEN:
			T.memory_write("Agent", self.agent, content, ignore_permissions=True)

	def test_a_case_that_asks_a_question_reports_recall_and_latency(self):
		report = E.evaluate_memory_case(
			scope="Agent",
			scope_key=self.agent,
			query="who approves invoices",
			expected_recall=[GOLDEN[0]],
			k=5,
		)
		self.assertIn("retrieval", report)
		self.assertIn("latency_ms", report)
		self.assertIn("within_budget", report)
		self.assertEqual(report["measured"], ["retrieval"])

	def test_a_case_that_measures_generation_reports_the_three_numbers(self):
		with _words_only():
			report = E.evaluate_memory_case(
				scope="Agent",
				scope_key=self.agent,
				golden_memories=GOLDEN,
				produced_memories=list(GOLDEN),
			)
		self.assertEqual(report["generation"]["f1"], 1.0)
		self.assertTrue(report["passed"])
		self.assertEqual(report["measured"], ["generation"])

	def test_a_poor_distillation_fails_the_case(self):
		with _words_only():
			report = E.evaluate_memory_case(
				scope="Agent", scope_key=self.agent, golden_memories=GOLDEN, produced_memories=["something else"]
			)
		self.assertFalse(report["passed"])

	def test_recall_outside_the_budget_fails_the_case(self):
		with patch.object(E, "timed", return_value=([], 999.0)):
			report = E.evaluate_memory_case(
				scope="Agent", scope_key=self.agent, query="anything", expected_recall=[]
			)
		self.assertFalse(report["within_budget"])
		self.assertFalse(report["passed"])

	def test_a_case_that_measures_nothing_cannot_fail(self):
		"""Otherwise a suite goes red because somebody wrote an empty case."""
		report = E.evaluate_memory_case(scope="Agent", scope_key=self.agent)
		self.assertTrue(report["passed"])
		self.assertEqual(report["measured"], [])


class TestTheRunnerRunsMemoryCases(FrappeTestCase):
	"""A Memory case measures the memory pipeline, so it needs no provider, no
	model and no map, and it must not be sent through the agent path."""

	def setUp(self):
		self.agent = f"EV_{frappe.generate_hash(length=8)}"
		for content in GOLDEN:
			T.memory_write("Agent", self.agent, content, ignore_permissions=True)

	def _case(self, **context):
		import json

		from one_bpmn.agents import eval_runner

		context.setdefault("scope", "Agent")
		context.setdefault("scope_key", self.agent)
		return eval_runner, frappe._dict(
			name="CASE-1",
			case_type="Memory",
			suite="SUITE-1",
			input_user_prompt=context.pop("query", ""),
			expected_output="\n".join(context.pop("golden_lines", [])),
			input_context=json.dumps(context),
			assertions=[],
		)

	def test_a_memory_case_never_reaches_the_agent(self):
		runner, case = self._case(query="who approves invoices", golden_lines=[GOLDEN[0]])
		with patch.object(runner, "_run_agent_eval", side_effect=AssertionError("should not run the agent")), patch.object(
			runner, "_run_direct_eval", side_effect=AssertionError("should not call a model")
		):
			row = runner._execute_case_inner(case)
		self.assertIn(row["status"], ("Passed", "Failed"))
		self.assertEqual(row["tokens_used"], 0)
		self.assertEqual(row["cost"], 0.0)

	def test_the_numbers_are_where_a_reader_looks_for_the_result(self):
		import json

		runner, case = self._case(query="who approves invoices", golden_lines=[GOLDEN[0]])
		row = runner._execute_case_inner(case)
		report = json.loads(row["actual_output"])
		self.assertIn("retrieval", report)
		self.assertIn("latency_ms", report)

	def test_a_case_with_no_scope_key_says_so(self):
		runner, case = self._case(query="anything")
		case.input_context = "{}"
		row = runner._execute_case_inner(case)
		self.assertEqual(row["status"], "Error")
		self.assertIn("scope_key", row["error_message"])

	def test_the_golden_memories_come_from_the_field_people_already_edit(self):
		runner, case = self._case(golden_lines=GOLDEN, produced_memories=list(GOLDEN))
		spec = runner._memory_case_spec(case)
		self.assertEqual(spec["golden_memories"], GOLDEN)
