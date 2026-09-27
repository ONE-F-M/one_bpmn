# Copyright (c) 2026, one-fm and contributors
"""Two quick messages must not corrupt one conversation.

Reproduced before the fix: two deliveries 100 ms apart each restored the same
workflow_state, and the transcript came back User, User, Bot, Bot with the
replies reversed. These cover the lock that serialises the turns and the id that
makes a redelivery free.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import turn_idempotency as idem
from one_bpmn.api import agent_invocation, server_script_api
from one_bpmn.security import turn_lock


class TestTurnLock(FrappeTestCase):
	def setUp(self):
		self.conv = f"conv-{frappe.generate_hash(length=8)}"

	def tearDown(self):
		try:
			frappe.cache().delete(turn_lock._key(self.conv))
		except Exception:
			pass

	def test_the_first_turn_takes_the_lock(self):
		token = turn_lock.acquire(self.conv)
		self.assertTrue(token)
		self.assertTrue(turn_lock.is_held(self.conv))
		turn_lock.release(self.conv, token)
		self.assertFalse(turn_lock.is_held(self.conv))

	def test_refuse_turns_the_second_message_away_at_once(self):
		token = turn_lock.acquire(self.conv)
		started = time.monotonic()
		with self.assertRaises(turn_lock.TurnBusy):
			turn_lock.acquire(self.conv, turn_lock.REFUSE)
		# Refusing must not sit on the connection waiting.
		self.assertLess(time.monotonic() - started, 0.5)
		turn_lock.release(self.conv, token)

	def test_queue_waits_and_then_takes_it(self):
		first = turn_lock.acquire(self.conv)
		got = {}
		site = frappe.local.site

		def second():
			frappe.init(site=site)
			frappe.connect()
			try:
				got["token"] = turn_lock.acquire(self.conv, turn_lock.QUEUE, wait_seconds=5)
			except Exception as e:  # surfaced by the assertion below
				got["error"] = repr(e)
			frappe.destroy()

		thread = threading.Thread(target=second)
		thread.start()
		time.sleep(0.5)
		# Still waiting — it has not jumped the running turn.
		self.assertNotIn("token", got)
		turn_lock.release(self.conv, first)
		thread.join(timeout=5)
		self.assertTrue(got.get("token"), got.get("error"))
		turn_lock.release(self.conv, got["token"])

	def test_a_queued_turn_gives_up_rather_than_hanging(self):
		token = turn_lock.acquire(self.conv)
		with self.assertRaises(turn_lock.TurnBusy):
			turn_lock.acquire(self.conv, turn_lock.QUEUE, wait_seconds=0.3)
		turn_lock.release(self.conv, token)

	def test_a_release_with_the_wrong_token_leaves_the_lock_alone(self):
		"""A turn that overran its TTL no longer owns the lock; freeing somebody
		else's turn would be worse than leaking this one."""
		token = turn_lock.acquire(self.conv)
		turn_lock.release(self.conv, "not-the-token")
		self.assertTrue(turn_lock.is_held(self.conv))
		turn_lock.release(self.conv, token)

	def test_no_conversation_means_nothing_to_lock(self):
		self.assertIsNone(turn_lock.acquire(""))
		turn_lock.release("", None)

	def test_redis_down_lets_the_turn_through(self):
		"""Fail open: a chat that refuses every message is worse than one that
		occasionally overlaps."""
		with patch.object(frappe, "cache", side_effect=Exception("redis gone")), patch.object(
			frappe, "log_error"
		):
			self.assertIsNone(turn_lock.acquire(self.conv))


class TestPolicyFor(FrappeTestCase):
	def test_an_unreadable_agent_queues(self):
		self.assertEqual(turn_lock.policy_for(None), turn_lock.QUEUE)

	def test_a_junk_value_queues_rather_than_guessing(self):
		with patch.object(frappe.db, "get_value", return_value="Whatever"):
			with patch("one_bpmn.security.pii._config_name", return_value="Some Agent"):
				self.assertEqual(turn_lock.policy_for("Some Agent"), turn_lock.QUEUE)

	def test_refuse_is_honoured(self):
		with patch.object(frappe.db, "get_value", return_value="Refuse"):
			with patch("one_bpmn.security.pii._config_name", return_value="Some Agent"):
				self.assertEqual(turn_lock.policy_for("Some Agent"), turn_lock.REFUSE)


class TestIdempotency(FrappeTestCase):
	def setUp(self):
		self.conv = frappe.get_doc(
			{"doctype": "Chat Conversation", "title": "idempotency test"}
		).insert(ignore_permissions=True)

	def test_an_unseen_id_is_not_a_replay(self):
		self.assertIsNone(idem.find_existing(self.conv.name, "never-sent"))

	def test_a_message_with_no_reply_yet_is_not_replayed(self):
		"""Mid-turn, or a turn that died. Re-running is right — a message with no
		answer is worse than a repeated one."""
		idem.record_user_message(self.conv.name, "hello", "id-1")
		self.assertIsNone(idem.find_existing(self.conv.name, "id-1"))

	def test_the_reply_is_returned_once_it_is_recorded(self):
		user = idem.record_user_message(self.conv.name, "hello", "id-2")
		reply = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conv.name,
				"text": "the answer",
				"message_type": "Bot",
			}
		).insert(ignore_permissions=True)
		idem.record_reply(user, reply.name)

		found = idem.find_existing(self.conv.name, "id-2")
		self.assertEqual(found["response"], "the answer")
		self.assertTrue(found["replayed"])

	def test_a_caller_supplied_message_is_stamped_not_duplicated(self):
		"""The Lumina page writes the user's row before it streams. Inserting a
		second one would put the same message in the transcript twice."""
		existing = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conv.name,
				"text": "already saved",
				"message_type": "User",
			}
		).insert(ignore_permissions=True)

		name = idem.record_user_message(self.conv.name, "already saved", "id-3", existing=existing.name)
		self.assertEqual(name, existing.name)
		self.assertEqual(
			frappe.db.get_value("Chat Message", existing.name, "client_message_id"), "id-3"
		)
		self.assertEqual(
			frappe.db.count("Chat Message", {"conversation": self.conv.name, "message_type": "User"}),
			1,
		)

	def test_ids_do_not_leak_between_conversations(self):
		idem.record_user_message(self.conv.name, "hello", "shared-id")
		other = frappe.get_doc({"doctype": "Chat Conversation", "title": "other"}).insert(
			ignore_permissions=True
		)
		self.assertIsNone(idem.find_existing(other.name, "shared-id"))


class TestTheControlIsChatOnly(FrappeTestCase):
	"""A Background agent has no conversation and no second message to order, so
	offering it the setting would be a control that decides nothing."""

	class _Agent:
		"""Only what agent_screening reads off the record."""

		def __init__(self, agent_type):
			self.name = "A"
			self.agent_type = agent_type

		def check_permission(self, *args, **kwargs):
			pass

		def has_permission(self, *args, **kwargs):
			return True

		def get(self, fieldname, default=None):
			return getattr(self, fieldname, default)

	def _screening(self, agent_type):
		from one_bpmn.api import security_api

		with patch.object(frappe, "get_doc", return_value=self._Agent(agent_type)):
			return security_api.agent_screening("A")

	def test_a_chat_agent_is_offered_the_setting(self):
		fields = [c["fieldname"] for c in self._screening("Chat")["controls"]]
		self.assertIn("concurrent_turn_policy", fields)

	def test_a_background_agent_is_not(self):
		fields = [c["fieldname"] for c in self._screening("Background")["controls"]]
		self.assertNotIn("concurrent_turn_policy", fields)
		# The rest of the controls are unaffected.
		self.assertIn("rate_limit_enabled", fields)

	def test_the_save_path_refuses_it_for_a_background_agent(self):
		from one_bpmn.api import security_api

		self.assertFalse(
			security_api._applies_to("concurrent_turn_policy", frappe._dict(agent_type="Background"))
		)
		self.assertTrue(
			security_api._applies_to("concurrent_turn_policy", frappe._dict(agent_type="Chat"))
		)
		self.assertTrue(
			security_api._applies_to("rate_limit_enabled", frappe._dict(agent_type="Background"))
		)


class TestStreamingTurnHoldsTheLock(FrappeTestCase):
	"""A map-driven chat turn streams, and the lock has to last as long as it does.

	_run_bpmn_map hands back {"streaming": True, "stream": <generator>} rather
	than the bare generator, which _is_stream did not recognise. The lock and the
	PII turn were torn down the moment the runner returned — eighty milliseconds
	in, with the map's first token still minutes of work away — so the setting
	serialised nothing for any agent whose map drives it.
	"""

	def _generator(self):
		yield {"type": "noop"}

	def test_the_envelope_a_map_runner_returns_counts_as_a_stream(self):
		gen = self._generator()
		self.assertTrue(agent_invocation._is_stream({"streaming": True, "stream": gen}))
		self.assertTrue(agent_invocation._is_stream(gen))
		gen.close()

	def test_a_buffered_reply_is_not_a_stream(self):
		self.assertFalse(agent_invocation._is_stream({"response": "hello"}))
		self.assertFalse(agent_invocation._is_stream({"streaming": True, "stream": None}))
		self.assertFalse(agent_invocation._is_stream(None))


class TestRedeliveryWhileTheMapReArms(FrappeTestCase):
	"""A message nobody catches must not become a five-minute wait.

	receive_message is quiet about a message no task was waiting for, and the
	caller then sat out CHAT_TURN_WAIT_SECONDS for a reply that could never
	come. The queued second message of a conversation met exactly that: the map
	writes the reply, reports the turn, and only then loops back to its gateway.
	"""

	class _Instance:
		def __init__(self, catches_on):
			self.catches_on = catches_on
			self.attempts = 0
			self.flags = frappe._dict()

		def receive_message(self, name, payload=None):
			self.attempts += 1
			self.flags.bpmn_message_caught = self.attempts >= self.catches_on

	def _run(self, catches_on, status="Active", seconds=1.0):
		instances = []

		def _get_doc(doctype, name):
			instances.append(self._Instance(catches_on - len(instances)))
			return instances[-1]

		with patch.object(server_script_api, "REARM_WAIT_SECONDS", seconds), patch.object(
			server_script_api, "_REARM_POLL_SECONDS", 0.05
		), patch.object(frappe.db, "commit"), patch.object(
			frappe.db, "get_value", return_value=status
		), patch.object(frappe, "get_doc", new=_get_doc):
			return server_script_api._redeliver_until_armed("inst", {})

	def test_it_keeps_trying_until_a_task_catches_the_message(self):
		self.assertTrue(self._run(catches_on=2))

	def test_it_gives_up_rather_than_trying_for_ever(self):
		self.assertFalse(self._run(catches_on=99))

	def test_an_instance_that_is_no_longer_running_is_not_retried(self):
		self.assertFalse(self._run(catches_on=1, status="Completed"))

