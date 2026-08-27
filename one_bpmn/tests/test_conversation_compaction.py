# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Conversation compaction: the summary replaces the covered range, once."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory.compaction import (
	SUMMARY_DOCTYPE,
	build_history,
	compact_conversation,
	latest_summary,
	needs_compaction,
	resolve_compaction_model,
)
from one_bpmn.agents.memory.conversation_store import (
	ContextWindowPolicy,
	SummarizingWindowPolicy,
)
from one_bpmn.utils.chat_persistence import (
	create_conversation,
	save_bot_message,
	save_user_message,
)

_SUMMARISE = "one_bpmn.agents.memory.compaction._summarise"


class TestSummarizingWindowPolicy(FrappeTestCase):
	"""Pure policy behaviour — no database, no model."""

	def _thread(self, n):
		return [
			{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
			for i in range(n)
		]

	def test_without_a_summary_it_matches_the_plain_policy(self):
		"""Configuring the policy before the first compaction must change nothing."""
		messages = self._thread(10)
		self.assertEqual(
			SummarizingWindowPolicy(max_messages=4).apply(messages),
			ContextWindowPolicy(max_messages=4).apply(messages),
		)

	def test_summary_comes_first_and_the_tail_follows(self):
		out = SummarizingWindowPolicy(max_messages=4, summary="earlier stuff").apply(
			self._thread(10)
		)
		self.assertEqual(len(out), 4)
		self.assertIn("earlier stuff", out[0]["content"])
		self.assertEqual([m["content"] for m in out[1:]], ["m7", "m8", "m9"])

	def test_the_summary_is_paid_for_out_of_the_budget(self):
		"""Adding a summary must not push the real message count over max_messages —
		otherwise turning compaction on silently grows the request."""
		for budget in (2, 3, 5, 8):
			with self.subTest(budget=budget):
				out = SummarizingWindowPolicy(
					max_messages=budget, summary="s"
				).apply(self._thread(20))
				self.assertLessEqual(len(out), budget)

	def test_the_system_prompt_survives_alongside_the_summary(self):
		messages = [{"role": "system", "content": "rules"}] + self._thread(10)
		out = SummarizingWindowPolicy(max_messages=4, summary="earlier").apply(messages)
		self.assertEqual(out[0]["role"], "system")
		self.assertIn("earlier", out[1]["content"])
		self.assertEqual(len(out), 4)

	def test_the_summary_role_is_configurable(self):
		out = SummarizingWindowPolicy(
			max_messages=3, summary="s", summary_role="assistant"
		).apply(self._thread(6))
		self.assertEqual(out[0]["role"], "assistant")


class TestConversationCompaction(FrappeTestCase):
	def setUp(self):
		self.conversation = create_conversation(
			agent_mode="one_bpmn:test-compaction",
			title=f"Compaction test {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		self.messages = []

	def _turns(self, n, prefix="turn"):
		"""n user/bot pairs, so the conversation reads like a real one."""
		for i in range(n):
			self.messages.append(save_user_message(self.conversation, f"{prefix} user {i}"))
			self.messages.append(save_bot_message(self.conversation, f"{prefix} bot {i}"))

	# ── reading, before anything is compacted ───────────────────────────
	def test_without_a_summary_it_returns_the_recent_tail(self):
		self._turns(6)  # 12 messages
		history = build_history(self.conversation, limit=4)
		self.assertEqual(len(history), 4)
		self.assertEqual(history[0]["content"], "turn user 4")
		self.assertEqual(history[-1]["content"], "turn bot 5")

	def test_an_unknown_conversation_reads_as_empty(self):
		self.assertEqual(build_history("does-not-exist"), [])

	# ── the acceptance criterion ────────────────────────────────────────
	def test_covered_messages_are_never_re_sent(self):
		self._turns(6)  # 12 messages
		with patch(_SUMMARISE, return_value="They discussed the first five turns."):
			out = compact_conversation(self.conversation, keep_tail=4, model="test-model")

		self.assertTrue(out["compacted"], out)
		self.assertEqual(out["covered_count"], 8)
		self.assertEqual(out["tail_kept"], 4)

		history = build_history(self.conversation, limit=4)
		# summary + exactly the four verbatim messages that follow it
		self.assertEqual(len(history), 5)
		self.assertIn("They discussed the first five turns.", history[0]["content"])
		self.assertEqual(
			[m["content"] for m in history[1:]],
			["turn user 4", "turn bot 4", "turn user 5", "turn bot 5"],
		)
		# and nothing from the covered range survives anywhere in it
		rendered = " ".join(m["content"] for m in history)
		for i in range(4):
			self.assertNotIn(f"turn user {i}", rendered)
			self.assertNotIn(f"turn bot {i}", rendered)

	def test_the_summary_records_the_exact_covered_range(self):
		self._turns(5)  # 10 messages
		with patch(_SUMMARISE, return_value="summary text"):
			compact_conversation(self.conversation, keep_tail=4, model="test-model")

		doc = frappe.get_doc(SUMMARY_DOCTYPE, latest_summary(self.conversation)["name"])
		self.assertEqual(doc.covered_from, self.messages[0])
		self.assertEqual(doc.covered_to, self.messages[5])
		self.assertEqual(doc.covered_count, 6)
		self.assertEqual(doc.model, "test-model")
		self.assertIsNone(doc.supersedes)

	# ── idempotence and chaining ────────────────────────────────────────
	def test_compacting_twice_with_nothing_new_does_nothing(self):
		self._turns(5)
		with patch(_SUMMARISE, return_value="first") as summarise:
			first = compact_conversation(self.conversation, keep_tail=4, model="m")
			second = compact_conversation(self.conversation, keep_tail=4, model="m")

		self.assertTrue(first["compacted"])
		self.assertFalse(second["compacted"])
		self.assertEqual(summarise.call_count, 1, "the model must not be called again")
		self.assertEqual(
			frappe.db.count(SUMMARY_DOCTYPE, {"conversation": self.conversation}), 1
		)

	def test_a_later_summary_absorbs_the_earlier_one(self):
		self._turns(5, prefix="early")
		with patch(_SUMMARISE, return_value="the early part"):
			compact_conversation(self.conversation, keep_tail=4, model="m")
		first = latest_summary(self.conversation)["name"]

		self._turns(5, prefix="late")
		with patch(_SUMMARISE, return_value="the whole thing so far") as summarise:
			compact_conversation(self.conversation, keep_tail=4, model="m")
			# the earlier summary is handed to the model to fold in, not discarded
			self.assertEqual(summarise.call_args.args[1], "the early part")

		second = frappe.get_doc(SUMMARY_DOCTYPE, latest_summary(self.conversation)["name"])
		self.assertNotEqual(second.name, first)
		self.assertEqual(second.supersedes, first)
		# cumulative: this summary stands in for its own range and the absorbed one
		self.assertEqual(second.covered_count, 16)

		history = build_history(self.conversation, limit=4)
		self.assertIn("the whole thing so far", history[0]["content"])
		self.assertNotIn("the early part", history[0]["content"])

	# ── failure must never lose history ─────────────────────────────────
	def test_a_failed_summariser_leaves_the_conversation_untouched(self):
		self._turns(5)
		before = build_history(self.conversation, limit=4)

		with patch(_SUMMARISE, return_value=None):
			out = compact_conversation(self.conversation, keep_tail=4, model="m")

		self.assertFalse(out["compacted"])
		self.assertEqual(frappe.db.count(SUMMARY_DOCTYPE, {"conversation": self.conversation}), 0)
		self.assertEqual(build_history(self.conversation, limit=4), before)

	def test_a_raising_summariser_is_swallowed(self):
		self._turns(5)
		with patch(_SUMMARISE, side_effect=RuntimeError("provider down")):
			out = compact_conversation(self.conversation, keep_tail=4, model="m")
		self.assertFalse(out["compacted"])
		self.assertEqual(out["reason"], "summariser raised")

	def test_nothing_above_the_tail_is_not_an_error(self):
		self._turns(2)  # 4 messages, tail of 4 covers everything
		with patch(_SUMMARISE) as summarise:
			out = compact_conversation(self.conversation, keep_tail=4, model="m")
		self.assertFalse(out["compacted"])
		summarise.assert_not_called()

	def test_without_a_model_it_declines_rather_than_guessing(self):
		self._turns(5)
		with patch(
			"one_bpmn.agents.memory.compaction.resolve_compaction_model", return_value=None
		), patch(_SUMMARISE) as summarise:
			out = compact_conversation(self.conversation, keep_tail=4)
		self.assertFalse(out["compacted"])
		self.assertEqual(out["reason"], "no model configured")
		summarise.assert_not_called()

	# ── the trigger predicate story 2.2 will call ───────────────────────
	def test_needs_compaction_tracks_the_uncovered_count(self):
		self._turns(2)  # 4 messages
		self.assertFalse(needs_compaction(self.conversation, keep_tail=4))
		self._turns(1)  # 6 messages
		self.assertTrue(needs_compaction(self.conversation, keep_tail=4))
		with patch(_SUMMARISE, return_value="s"):
			compact_conversation(self.conversation, keep_tail=4, model="m")
		self.assertFalse(needs_compaction(self.conversation, keep_tail=4))


class TestCompactionModelResolution(FrappeTestCase):
	def test_an_explicit_model_wins(self):
		self.assertEqual(resolve_compaction_model("explicit", "fallback"), "explicit")

	def test_the_site_default_beats_the_fallback(self):
		with patch("frappe.db.get_single_value", return_value="site-default"):
			self.assertEqual(resolve_compaction_model(None, "fallback"), "site-default")

	def test_the_fallback_is_the_last_resort(self):
		with patch("frappe.db.get_single_value", return_value=None):
			self.assertEqual(resolve_compaction_model(None, "fallback"), "fallback")

	def test_an_unreadable_setting_does_not_break_resolution(self):
		with patch("frappe.db.get_single_value", side_effect=Exception("boom")):
			self.assertEqual(resolve_compaction_model(None, "fallback"), "fallback")


class TestSummaryValidation(FrappeTestCase):
	def setUp(self):
		self.conversation = create_conversation(
			agent_mode="one_bpmn:test-compaction",
			title=f"Validation test {frappe.generate_hash(length=8)}",
			user="Administrator",
		)

	def _summary(self, **overrides):
		values = {
			"doctype": SUMMARY_DOCTYPE,
			"conversation": self.conversation,
			"summary": "text",
			"covered_upto": frappe.utils.now_datetime(),
			"covered_count": 3,
		}
		values.update(overrides)
		return frappe.get_doc(values)

	def test_a_summary_must_cover_something(self):
		with self.assertRaises(frappe.ValidationError):
			self._summary(covered_count=0).insert(ignore_permissions=True)

	def test_a_summary_must_record_where_it_reaches(self):
		with self.assertRaises(frappe.ValidationError):
			self._summary(covered_upto=None).insert(ignore_permissions=True)

	def test_a_chain_cannot_cross_conversations(self):
		"""A foreign cursor would hide another conversation's messages — the one
		failure here that loses content rather than merely wasting tokens."""
		other = create_conversation(
			agent_mode="one_bpmn:test-compaction",
			title=f"Other {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		foreign = frappe.get_doc(
			{
				"doctype": SUMMARY_DOCTYPE,
				"conversation": other,
				"summary": "text",
				"covered_upto": frappe.utils.now_datetime(),
				"covered_count": 1,
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._summary(supersedes=foreign.name).insert(ignore_permissions=True)
