"""The chat turn runs on the worker, and the request waits for it (WI-002363)."""

import time

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import turn_signal
from one_bpmn.api import server_script_api


def _instance_name() -> str:
	return "_test_turn_" + frappe.generate_hash(length=8)


class TestTurnSignal(FrappeTestCase):
	def test_a_published_signal_ends_the_wait(self):
		instance = _instance_name()
		turn_signal.publish(instance)

		started = time.monotonic()
		self.assertTrue(turn_signal.wait(instance, timeout=5))
		self.assertLess(time.monotonic() - started, 2)

	def test_waiting_without_a_signal_gives_up_at_the_deadline(self):
		started = time.monotonic()

		self.assertFalse(turn_signal.wait(_instance_name(), timeout=0.5, poll_seconds=0.05))

		elapsed = time.monotonic() - started
		self.assertGreaterEqual(elapsed, 0.5)
		self.assertLess(elapsed, 5)

	def test_a_signal_is_consumed_once(self):
		instance = _instance_name()
		turn_signal.publish(instance)

		self.assertTrue(turn_signal.wait(instance, timeout=5))
		self.assertFalse(turn_signal.wait(instance, timeout=0.2, poll_seconds=0.05))

	def test_clear_drops_a_signal_left_by_an_earlier_turn(self):
		instance = _instance_name()
		turn_signal.publish(instance)

		turn_signal.clear(instance)

		self.assertFalse(turn_signal.wait(instance, timeout=0.2, poll_seconds=0.05))

	def test_one_instance_signal_does_not_end_another_instance_wait(self):
		mine, other = _instance_name(), _instance_name()
		turn_signal.publish(other)

		self.assertFalse(turn_signal.wait(mine, timeout=0.2, poll_seconds=0.05))
		self.assertTrue(turn_signal.wait(other, timeout=5))


class TestWaitForWorkerReply(FrappeTestCase):
	def test_the_wait_is_skipped_under_test_so_a_suite_cannot_hang(self):
		"""Parking is off in tests, so the reply already exists when this is
		reached. Without the guard every delegation test would block for the
		full turn deadline."""
		started = time.monotonic()

		result = server_script_api._wait_for_worker_reply(_instance_name(), "_test_conversation", None)

		self.assertIsNone(result)
		self.assertLess(time.monotonic() - started, 1)

	def test_the_request_no_longer_forces_the_agent_to_run_inline(self):
		"""The flag that kept the model call inside the web worker is gone."""
		import inspect

		source = inspect.getsource(server_script_api._delegate_to_bpmn_instance)
		self.assertNotIn("bpmn_disable_ai_parking", source)


class TestTheRequestPicksUpTheWorkerReply(FrappeTestCase):
	"""The whole point of the change: the request hands the turn to the worker
	and still returns that turn's reply."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = "_test_conv_" + frappe.generate_hash(length=8)
		self.instance = _instance_name()
		# Say the turn really did park, so the wait runs instead of assuming an
		# inline engine pass already produced the reply.
		frappe.flags.bpmn_force_ai_parking = True

	def tearDown(self):
		frappe.flags.bpmn_force_ai_parking = False

	def _bot_message(self, text):
		doc = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation,
				"message_type": "Bot",
				"text": text,
			}
		)
		doc.flags.ignore_links = True
		doc.flags.ignore_mandatory = True
		return doc.insert(ignore_permissions=True)

	def test_the_reply_the_worker_wrote_is_what_comes_back(self):
		from unittest.mock import patch

		reply = self._bot_message("the worker answered")
		turn_signal.publish(self.instance)

		# The two commits are what the real path needs and what a test must not
		# do: committing here would defeat the suite's rollback.
		with patch.object(frappe.db, "commit"):
			rows = server_script_api._wait_for_worker_reply(self.instance, self.conversation, None)

		self.assertIsNotNone(rows)
		self.assertEqual(rows[0]["name"], reply.name)
		self.assertEqual(rows[0]["text"], "the worker answered")

	def test_a_turn_that_produced_nothing_new_reports_nothing(self):
		from unittest.mock import patch

		earlier = self._bot_message("last turn's answer")
		turn_signal.publish(self.instance)

		with patch.object(frappe.db, "commit"):
			rows = server_script_api._wait_for_worker_reply(self.instance, self.conversation, earlier.name)

		self.assertIsNone(rows)

	def test_a_worker_that_never_answers_ends_at_the_deadline(self):
		from unittest.mock import patch

		with (
			patch.object(frappe.db, "commit"),
			patch.object(server_script_api, "CHAT_TURN_WAIT_SECONDS", 0.5),
		):
			rows = server_script_api._wait_for_worker_reply(self.instance, self.conversation, None)

		self.assertIsNone(rows)
