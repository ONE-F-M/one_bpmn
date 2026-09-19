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
