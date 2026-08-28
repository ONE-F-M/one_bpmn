# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Compaction triggers: three questions, one queue, never on the hot path."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.memory import compaction_triggers as triggers
from one_bpmn.agents.memory.compaction_triggers import (
	COMPACTION_QUEUE,
	enqueue_compaction,
	estimated_history_tokens,
	on_chat_message,
	run_compaction,
	sweep_idle_conversations,
	trigger_config,
)
from one_bpmn.utils.chat_persistence import (
	create_conversation,
	save_bot_message,
	save_user_message,
)

_ENQUEUE = "frappe.enqueue"
_COMPACT = "one_bpmn.agents.memory.compaction.compact_conversation"

# Long enough that the conversation clears the worth-it threshold in compaction.
_USER = " and please keep the existing naming convention consistent throughout"
_BOT = (
	" I have applied that change and left the rest of the schema alone, so every "
	"other field keeps the settings you chose earlier in this conversation."
)


class CompactionTriggerCase(FrappeTestCase):
	"""One agent, one conversation, compaction configured however the test needs."""

	def setUp(self):
		# chat_mode_label is unique across ENABLED agents, so the label has to be
		# per-test too — a shared one collides as soon as a second test runs.
		suffix = frappe.generate_hash(length=6)
		self.agent_id = f"_test_compaction_{suffix}"
		self.MODE = f"_Test Compaction {suffix}"
		self.config = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_id": self.agent_id,
				"agent_name": self.agent_id,
				"chat_mode_label": self.MODE,
				"enabled": 1,
				"compaction_enabled": 1,
				"compaction_keep_tail": 4,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)

		self.conversation = create_conversation(
			agent_mode=self.MODE,
			title=f"Trigger test {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		triggers._clear_inflight(self.conversation)

	def tearDown(self):
		triggers._clear_inflight(self.conversation)
		# Inserting an AI Agent Configuration fires the agent-creation map, which
		# COMMITS — so the row and the instance it spawns survive the test
		# rollback. Left alone, every run adds a config, a conversation and a
		# BPMN instance to the site permanently; 178 of them had accumulated
		# before this was noticed, and each one also makes the next run slower.
		frappe.flags.in_migrate = True
		try:
			frappe.db.delete("Chat Conversation Summary", {"conversation": self.conversation})
			frappe.db.delete("Chat Message", {"conversation": self.conversation})
			frappe.db.delete("Chat Conversation", {"name": self.conversation})
			for inst in frappe.get_all(
				"BPMN Process Instance", filters={"context_docname": self.config.name}, pluck="name"
			):
				frappe.delete_doc("BPMN Process Instance", inst, force=True,
				                  ignore_permissions=True, delete_permanently=True)
			frappe.delete_doc("AI Agent Configuration", self.config.name, force=True,
			                  ignore_permissions=True, delete_permanently=True)
			frappe.db.commit()
		except Exception:
			# A cleanup failure must not mask the result of the test itself.
			frappe.db.rollback()
		finally:
			frappe.flags.in_migrate = False

	def _configure(self, **values):
		for k, v in values.items():
			self.config.db_set(k, v, update_modified=False)
		self.config.reload()

	def _turns(self, n):
		# The hook is live, so seeding would queue REAL jobs — and a worker
		# picking one up mid-test clears the in-flight marker underneath the
		# assertion. Fixtures must not spawn background work.
		with patch(_ENQUEUE):
			for i in range(n):
				save_user_message(self.conversation, f"user {i}{_USER}")
				save_bot_message(self.conversation, f"bot {i}{_BOT}")
		# Seeding writes real Chat Messages, which fire the real hook — so the
		# fixture can leave the conversation already marked in flight and the
		# assertion under test would then be measuring the setup. Clearing here
		# rather than in setUp because _turns is what does the writing.
		triggers._clear_inflight(self.conversation)


class TestTriggerConfig(CompactionTriggerCase):
	def test_a_disabled_agent_has_no_config(self):
		self._configure(compaction_enabled=0)
		self.assertIsNone(trigger_config(self.agent_id))

	def test_an_unknown_agent_has_no_config(self):
		self.assertIsNone(trigger_config("no_such_agent"))
		self.assertIsNone(trigger_config(None))

	def test_keep_tail_falls_back_rather_than_becoming_zero(self):
		"""A keep_tail of 0 would cover the entire conversation including the
		turn just spoken — never what an unset field should mean."""
		self._configure(compaction_keep_tail=0)
		self.assertEqual(trigger_config(self.agent_id)["keep_tail"], 10)


class TestNeverInline(CompactionTriggerCase):
	"""The acceptance criterion that matters most: enqueued, never inline."""

	def test_the_hook_queues_and_does_not_summarise(self):
		self._configure(compaction_on_task_boundary=1)
		self._turns(6)

		with patch(_COMPACT) as compact, patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="Bot", text="hi")
			)

		compact.assert_not_called()
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["queue"], COMPACTION_QUEUE)
		self.assertEqual(
			enqueue.call_args.args[0],
			"one_bpmn.agents.memory.compaction_triggers.run_compaction",
		)

	def test_writing_a_message_never_summarises_on_the_request_thread(self):
		"""The end-to-end version: a real insert, through the real hook."""
		self._configure(compaction_on_task_boundary=1)
		self._turns(6)
		with patch(_COMPACT) as compact, patch(_ENQUEUE):
			save_bot_message(self.conversation, "a reply that ends the turn")
		compact.assert_not_called()

	def test_a_hook_failure_never_breaks_the_chat(self):
		self._configure(compaction_on_task_boundary=1)
		with patch.object(triggers, "trigger_config", side_effect=RuntimeError("boom")):
			# Must not raise — the message still has to be written.
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="Bot", text="hi")
			)


class TestCountTrigger(CompactionTriggerCase):
	def test_it_queues_once_the_history_outgrows_the_threshold(self):
		self._configure(compaction_token_threshold=20)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="User", text="x")
			)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["reason"], "token-threshold")

	def test_it_stays_quiet_below_the_threshold(self):
		self._configure(compaction_token_threshold=100000)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="User", text="x")
			)
		enqueue.assert_not_called()

	def test_a_zero_threshold_disables_the_count_trigger(self):
		self._configure(compaction_token_threshold=0)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="User", text="x")
			)
		enqueue.assert_not_called()

	def test_the_estimate_measures_what_would_be_sent(self):
		"""Not a row count — so once a summary exists the number drops and the
		threshold stops re-firing on history that is no longer sent."""
		self._turns(12)  # enough covered prose to clear compaction's worth-it gate
		before = estimated_history_tokens(self.conversation, 20)
		self.assertGreater(before, 0)
		with patch(
			"one_bpmn.agents.memory.compaction._summarise", return_value="A short summary."
		):
			from one_bpmn.agents.memory.compaction import compact_conversation

			compact_conversation(self.conversation, keep_tail=4, model="m")
		self.assertLess(estimated_history_tokens(self.conversation, 20), before)


class TestEventTrigger(CompactionTriggerCase):
	def test_it_fires_when_the_agent_replies(self):
		self._configure(compaction_on_task_boundary=1)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="Bot", text="x")
			)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["reason"], "turn-boundary")

	def test_it_does_not_fire_part_way_through_a_turn(self):
		"""A user message is the START of a turn — compacting there would change
		the history under an agent that is about to read it."""
		self._configure(compaction_on_task_boundary=1)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="User", text="x")
			)
		enqueue.assert_not_called()

	def test_a_system_message_is_ignored_entirely(self):
		self._configure(compaction_on_task_boundary=1)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			on_chat_message(
				frappe._dict(conversation=self.conversation, message_type="Tool", text="x")
			)
		enqueue.assert_not_called()


class TestTimeTrigger(CompactionTriggerCase):
	def _age_the_conversation(self, minutes):
		frappe.db.sql(
			"UPDATE `tabChat Message` SET creation = %s WHERE conversation = %s",
			(add_to_date(now_datetime(), minutes=-minutes), self.conversation),
		)

	def _queued(self, mock):
		"""Conversations this sweep queued. The sweep is site-wide, so asserting
		on the global call count would make every test depend on what the rest
		of the suite left behind."""
		return [c.kwargs.get("conversation") for c in mock.call_args_list]

	def test_it_queues_a_conversation_that_has_gone_quiet(self):
		self._configure(compaction_idle_minutes=30)
		self._turns(6)
		self._age_the_conversation(120)
		with patch(_ENQUEUE) as enqueue:
			sweep_idle_conversations()
		self.assertIn(self.conversation, self._queued(enqueue))
		mine = [c for c in enqueue.call_args_list
		        if c.kwargs.get("conversation") == self.conversation]
		self.assertEqual(mine[0].kwargs["reason"], "idle")

	def test_it_leaves_a_live_conversation_alone(self):
		self._configure(compaction_idle_minutes=30)
		self._turns(6)  # just now
		with patch(_ENQUEUE) as enqueue:
			sweep_idle_conversations()
		self.assertNotIn(self.conversation, self._queued(enqueue))

	def test_an_agent_without_an_idle_threshold_is_not_swept(self):
		self._configure(compaction_idle_minutes=0)
		self._turns(6)
		self._age_the_conversation(600)
		with patch(_ENQUEUE) as enqueue:
			sweep_idle_conversations()
		self.assertNotIn(self.conversation, self._queued(enqueue))


class TestTriggersBehaveEquivalently(CompactionTriggerCase):
	"""The AC's real requirement: whichever trigger fires, the same work runs."""

	def _queued_job(self, fire):
		with patch(_ENQUEUE) as enqueue:
			fire()
		mine = [c for c in enqueue.call_args_list
		        if c.kwargs.get("conversation") == self.conversation]
		self.assertTrue(mine, "expected this trigger to queue work")
		kwargs = dict(mine[0].kwargs)
		kwargs.pop("reason")
		return mine[0].args[0], kwargs

	def test_all_three_queue_the_identical_job(self):
		self._turns(6)

		self._configure(compaction_token_threshold=20, compaction_on_task_boundary=0,
		                compaction_idle_minutes=0)
		count = self._queued_job(lambda: on_chat_message(
			frappe._dict(conversation=self.conversation, message_type="User", text="x")))

		triggers._clear_inflight(self.conversation)
		self._configure(compaction_token_threshold=0, compaction_on_task_boundary=1)
		event = self._queued_job(lambda: on_chat_message(
			frappe._dict(conversation=self.conversation, message_type="Bot", text="x")))

		triggers._clear_inflight(self.conversation)
		self._configure(compaction_on_task_boundary=0, compaction_idle_minutes=30)
		frappe.db.sql(
			"UPDATE `tabChat Message` SET creation = %s WHERE conversation = %s",
			(add_to_date(now_datetime(), minutes=-120), self.conversation),
		)
		idle = self._queued_job(sweep_idle_conversations)

		self.assertEqual(count, event)
		self.assertEqual(event, idle)


class TestInFlightGuard(CompactionTriggerCase):
	def test_a_burst_of_messages_queues_the_work_once(self):
		self._configure(compaction_on_task_boundary=1)
		self._turns(6)
		with patch(_ENQUEUE) as enqueue:
			for _ in range(5):
				on_chat_message(
					frappe._dict(conversation=self.conversation, message_type="Bot", text="x")
				)
		self.assertEqual(enqueue.call_count, 1)

	def test_nothing_to_compact_does_not_take_the_marker(self):
		"""Otherwise one early trigger would suppress the real one for fifteen
		minutes, on a conversation that had nothing to compact at the time."""
		self._configure(compaction_on_task_boundary=1)
		with patch(_ENQUEUE) as enqueue:
			enqueue_compaction(self.conversation, reason="turn-boundary")
		enqueue.assert_not_called()
		self.assertFalse(triggers._is_inflight(self.conversation))

	def test_the_marker_is_released_however_the_job_ends(self):
		self._turns(6)
		triggers._mark_inflight(self.conversation, "turn-boundary")
		with patch(_COMPACT, side_effect=RuntimeError("provider down")):
			out = run_compaction(self.conversation, keep_tail=4)
		self.assertFalse(out["compacted"])
		self.assertFalse(
			triggers._is_inflight(self.conversation),
			"a failed job must not lock the conversation out of compaction",
		)


class TestTheJob(CompactionTriggerCase):
	def test_the_job_is_the_only_caller_of_compaction(self):
		self._turns(6)
		with patch(_COMPACT, return_value={"compacted": True}) as compact:
			run_compaction(self.conversation, agent_id=self.agent_id, keep_tail=4, model="m")
		compact.assert_called_once()
		self.assertEqual(compact.call_args.kwargs["keep_tail"], 4)
		self.assertEqual(compact.call_args.kwargs["model"], "m")
		self.assertEqual(compact.call_args.kwargs["agent_id"], self.agent_id)

	def test_the_job_never_raises(self):
		with patch(_COMPACT, side_effect=RuntimeError("boom")):
			out = run_compaction(self.conversation, keep_tail=4)
		self.assertFalse(out["compacted"])
		self.assertEqual(out["reason"], "job raised")
