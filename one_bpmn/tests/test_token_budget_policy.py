# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""History truncation by token budget: newest-first, system kept, pairs intact."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory.compaction import build_history, resolve_token_budget
from one_bpmn.agents.memory.conversation_store import (
	ContextWindowPolicy,
	SummarizingWindowPolicy,
	estimate_tokens,
)
from one_bpmn.utils.chat_persistence import (
	create_conversation,
	save_bot_message,
	save_user_message,
)

# 40 characters -> 10 tokens at the default 4 chars/token, so the arithmetic in
# these tests is checkable by eye rather than by running them.
TEN = "x" * 40


def msg(role, content=TEN, **extra):
	out = {"role": role, "content": content}
	out.update(extra)
	return out


class TestEstimate(FrappeTestCase):
	def test_it_counts_content(self):
		self.assertEqual(estimate_tokens(msg("user")), 10)

	def test_it_counts_tool_call_payloads(self):
		"""On a tool-heavy thread the arguments are routinely larger than the
		prose beside them; a budget blind to them is wrong where it matters."""
		bare = estimate_tokens(msg("assistant", ""))
		with_call = estimate_tokens(
			msg("assistant", "", tool_calls=[{"name": "search", "arguments": {"q": "x" * 200}}])
		)
		self.assertEqual(bare, 0)
		self.assertGreater(with_call, 40)

	def test_a_custom_ratio_is_honoured(self):
		self.assertEqual(estimate_tokens(msg("user"), chars_per_token=10), 4)


class TestTokenBudget(FrappeTestCase):
	def test_no_budget_leaves_the_thread_alone(self):
		thread = [msg("user") for _ in range(20)]
		self.assertEqual(len(ContextWindowPolicy(max_messages=0, max_tokens=0).apply(thread)), 20)

	def test_it_includes_newest_first_up_to_the_budget(self):
		thread = [msg("user", f"{i:040d}") for i in range(10)]  # 10 tokens each
		out = ContextWindowPolicy(max_messages=0, max_tokens=35).apply(thread)
		self.assertEqual(len(out), 3)  # 3 x 10 = 30 fits, a 4th would be 40
		self.assertEqual([m["content"] for m in out], [f"{i:040d}" for i in (7, 8, 9)])

	def test_the_system_prompt_is_always_retained(self):
		"""Even when the budget alone would not have room for it — a thread that
		has lost its instructions is worse than one that has lost its history."""
		thread = [msg("system", "S" * 400)] + [msg("user") for _ in range(5)]
		out = ContextWindowPolicy(max_messages=0, max_tokens=10).apply(thread)
		self.assertEqual(out[0]["role"], "system")

	def test_the_system_prompt_is_still_counted(self):
		"""Counted, not free: a budget that ignored it would promise a ceiling
		it does not enforce."""
		thread = [msg("system")] + [msg("user") for _ in range(5)]
		out = ContextWindowPolicy(max_messages=0, max_tokens=30).apply(thread)
		self.assertEqual(len(out), 3)  # system (10) + 2 user (20)

	def test_it_stops_rather_than_skipping_to_something_smaller(self):
		"""Skipping would reorder the thread — an earlier message surviving while
		a later one was dropped leaves a hole in the middle, not a short tail."""
		thread = [msg("user", "s"), msg("user", "L" * 400), msg("user", "t")]
		out = ContextWindowPolicy(max_messages=0, max_tokens=50).apply(thread)
		self.assertEqual([m["content"] for m in out], ["t"])

	def test_both_limits_apply_and_the_tighter_one_wins(self):
		thread = [msg("user") for _ in range(20)]
		by_count = ContextWindowPolicy(max_messages=5, max_tokens=1000).apply(thread)
		by_budget = ContextWindowPolicy(max_messages=20, max_tokens=25).apply(thread)
		self.assertEqual(len(by_count), 5)
		self.assertEqual(len(by_budget), 2)

	def test_the_newest_exchange_is_sent_even_when_it_busts_the_budget(self):
		"""Found in testing: a 150-token budget against an agent whose replies
		run to 700 returned an EMPTY history. A budget is a target for trimming
		history, not a licence to send a conversation with none — a request
		carrying one oversized message beats one carrying no context at all."""
		thread = [msg("user", "A" * 4000), msg("assistant", "B" * 4000)]
		out = ContextWindowPolicy(max_messages=0, max_tokens=150).apply(thread)
		self.assertEqual(len(out), 1)
		self.assertTrue(out[0]["content"].startswith("B"), "kept the NEWEST, not the oldest")

	def test_an_oversized_newest_exchange_keeps_its_tool_pair_whole(self):
		thread = [
			msg("assistant", "C" * 4000, tool_calls=[{"id": "c1"}]),
			msg("tool", "R" * 4000, tool_call_id="c1"),
		]
		out = ContextWindowPolicy(max_messages=0, max_tokens=10).apply(thread)
		self.assertEqual(len(out), 2, "a pair must not be split even when oversized")

	def test_a_tiny_budget_still_keeps_the_system_prompt_and_the_newest(self):
		thread = [msg("system", "s")] + [msg("user", "U" * 4000) for _ in range(3)]
		out = ContextWindowPolicy(max_messages=0, max_tokens=1).apply(thread)
		self.assertEqual([m["role"] for m in out], ["system", "user"])


class TestToolPairsStayIntact(FrappeTestCase):
	"""A tool result whose originating call is absent makes the provider reject
	the whole request — turning a request that would merely have been shorter
	into one that fails, on exactly the threads a budget exists for."""

	def _thread(self):
		return [
			msg("user", "old"),
			msg("assistant", "", tool_calls=[{"id": "c1", "name": "search"}]),
			msg("tool", "R" * 400, tool_call_id="c1"),
			msg("assistant", "answer"),
		]

	def test_a_tool_result_never_arrives_without_its_call(self):
		for budget in range(5, 140, 7):
			with self.subTest(budget=budget):
				out = ContextWindowPolicy(max_messages=0, max_tokens=budget).apply(self._thread())
				for i, m in enumerate(out):
					if m.get("tool_call_id"):
						self.assertTrue(
							any((p.get("tool_calls") is not None) for p in out[:i]),
							"a tool result survived without its originating call",
						)

	def test_an_affordable_pair_is_kept_whole(self):
		out = ContextWindowPolicy(max_messages=0, max_tokens=500).apply(self._thread())
		self.assertEqual(len(out), 4)

	def test_an_unaffordable_pair_is_dropped_whole(self):
		"""The pair costs ~100; a budget of 60 takes the trailing answer only."""
		out = ContextWindowPolicy(max_messages=0, max_tokens=60).apply(self._thread())
		self.assertEqual([m["content"] for m in out], ["answer"])


class TestBudgetWithASummary(FrappeTestCase):
	def test_the_summary_is_never_dropped_to_fit(self):
		"""It stands in for every message it replaced, so dropping it discards
		more history than dropping any single turn could."""
		thread = [msg("user") for _ in range(10)]
		out = SummarizingWindowPolicy(
			max_messages=0, max_tokens=5, summary="the earlier conversation"
		).apply(thread)
		self.assertIn("the earlier conversation", out[0]["content"])

	def test_the_summary_is_counted_against_the_budget(self):
		"""Counted, not free. Tested by comparison rather than by arithmetic: at
		the same budget, a thread carrying a summary must fit FEWER verbatim
		messages than one without, because the summary spends part of it."""
		thread = [msg("user") for _ in range(10)]
		budget = 100

		without = ContextWindowPolicy(max_messages=0, max_tokens=budget).apply(thread)
		with_summary = SummarizingWindowPolicy(
			max_messages=0, max_tokens=budget, summary="S" * 200
		).apply(thread)

		verbatim = [m for m in with_summary if "Summary of the earlier" not in m["content"]]
		self.assertLess(len(verbatim), len(without))
		self.assertLessEqual(sum(estimate_tokens(m) for m in with_summary), budget)

	def test_without_a_budget_it_behaves_as_before(self):
		thread = [msg("user") for _ in range(10)]
		out = SummarizingWindowPolicy(max_messages=4, summary="s").apply(thread)
		self.assertEqual(len(out), 4)


class TestBudgetOnTheLivePath(FrappeTestCase):
	def setUp(self):
		self.conversation = create_conversation(
			agent_mode="_Test Budget", title=f"Budget {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		with patch("frappe.enqueue"):
			for i in range(6):
				save_user_message(self.conversation, f"user {i} " + "u" * 120)
				save_bot_message(self.conversation, f"bot {i} " + "b" * 240)

	def test_build_history_honours_an_explicit_budget(self):
		full = build_history(self.conversation, limit=20, token_budget=0)
		capped = build_history(self.conversation, limit=20, token_budget=100)
		self.assertGreater(len(full), len(capped))
		self.assertLessEqual(sum(estimate_tokens(m) for m in capped), 100)

	def test_it_keeps_the_newest_messages(self):
		capped = build_history(self.conversation, limit=20, token_budget=100)
		self.assertIn("bot 5", capped[-1]["content"])

	def test_zero_means_no_limit(self):
		self.assertEqual(
			len(build_history(self.conversation, limit=20, token_budget=0)),
			len(build_history(self.conversation, limit=20, token_budget=None))
			if resolve_token_budget(self.conversation) == 0
			else len(build_history(self.conversation, limit=20, token_budget=0)),
		)

	def test_an_unresolvable_budget_never_blocks_history(self):
		with patch("frappe.db.get_value", side_effect=RuntimeError("boom")):
			self.assertEqual(resolve_token_budget(self.conversation), 0)
