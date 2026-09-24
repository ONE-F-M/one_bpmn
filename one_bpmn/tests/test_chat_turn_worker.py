"""The chat turn runs on the worker, and the request waits for it."""

import time
from unittest.mock import patch

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
		# Force the parked path, or the wait is skipped.
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

		# A real commit here would defeat the suite's rollback.
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


class TestProgressReachesTheRequest(FrappeTestCase):
	"""A tool announces itself from the worker and the request relays it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.instance = _instance_name()

	def test_a_tool_announces_its_start_and_its_end(self):
		from one_bpmn.agents import shape_tools

		instance = frappe._dict({"name": self.instance, "_service_task_extensions": {}})
		# Even the early return has to close its status line.
		shape_tools.execute_shape(instance, "draft_connector", {}, {})

		events = list(turn_signal.consume(self.instance, timeout=0.5, poll_seconds=0.05))
		self.assertEqual(
			[(e["type"], e["toolCallName"]) for e in events],
			[("TOOL_CALL_START", "draft_connector"), ("TOOL_CALL_END", "draft_connector")],
		)

	def test_a_deferred_tool_does_not_close_its_status_line(self):
		from unittest.mock import patch

		from one_bpmn.agents import shape_tools

		instance = frappe._dict({"name": self.instance, "_service_task_extensions": {}})
		with patch.object(
			shape_tools, "_run_server_script", side_effect=shape_tools.ToolDeferred({"waiting": "sandbox"})
		):
			with self.assertRaises(shape_tools.ToolDeferred):
				shape_tools.execute_shape(instance, "run_tests", {"serverScript": "X"}, {})

		events = list(turn_signal.consume(self.instance, timeout=0.5, poll_seconds=0.05))
		self.assertEqual([e["type"] for e in events], ["TOOL_CALL_START"])

	def test_the_handover_leaves_the_relay_and_carries_the_reply(self):
		from one_bpmn.agents.agui_stream import HANDOVER_EVENT, _take_handover

		child = iter(
			[
				{"type": "TOOL_CALL_START", "toolCallName": "inspect"},
				{"type": HANDOVER_EVENT, "result": {"response": "done"}},
			]
		)
		handover = {}

		relayed = list(_take_handover(child, handover))

		self.assertEqual([e["type"] for e in relayed], ["TOOL_CALL_START"])
		self.assertEqual(handover["result"], {"response": "done"})

	def test_a_stream_that_ends_without_a_handover_says_so(self):
		from one_bpmn.agents.agui_stream import _take_handover

		handover = {}

		list(_take_handover(iter([{"type": "TOOL_CALL_START", "toolCallName": "x"}]), handover))

		self.assertNotIn("result", handover)


class TestTheReplyComesFromTheTaskOutput(FrappeTestCase):
	"""The answer is the AI task's own output, not whatever row happened to be
	newest when the request looked."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = "_test_conv_" + frappe.generate_hash(length=8)
		self.instance = _instance_name()
		frappe.flags.bpmn_force_ai_parking = True
		# No worker here, so an unbounded wait would hang the suite.
		self._wait_patch = patch.object(server_script_api, "CHAT_TURN_WAIT_SECONDS", 0.3)
		self._wait_patch.start()

	def tearDown(self):
		self._wait_patch.stop()
		frappe.flags.bpmn_force_ai_parking = False

	def _bot_message(self, text, metadata=None):
		doc = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation,
				"message_type": "Bot",
				"text": text,
				"metadata": metadata,
			}
		)
		doc.flags.ignore_links = True
		doc.flags.ignore_mandatory = True
		return doc.insert(ignore_permissions=True)

	def _handle(self, reply_before=None):
		return {
			"instance": self.instance,
			"conversation": self.conversation,
			"reply_before": reply_before,
			"turn_started": frappe.utils.now_datetime(),
		}

	def test_the_task_output_wins_over_the_metadata_on_the_row(self):
		import json as _json

		row = self._bot_message("row text", _json.dumps({"agent_result": {"response": "from the row"}}))

		with patch.object(frappe.db, "commit"):
			result = server_script_api.collect_chat_turn_reply(
				self._handle(), {"response": "from the task", "intent": "ANSWER"}
			)

		self.assertEqual(result["response"], "from the task")
		self.assertEqual(result["intent"], "ANSWER")
		self.assertEqual(result["message_name"], row.name)

	def test_without_a_task_output_the_row_still_answers(self):
		import json as _json

		self._bot_message("row text", _json.dumps({"agent_result": {"response": "from the row"}}))

		with patch.object(frappe.db, "commit"):
			result = server_script_api.collect_chat_turn_reply(self._handle())

		self.assertEqual(result["response"], "from the row")

	def test_a_turn_that_saved_no_message_still_answers_from_its_output(self):
		with patch.object(frappe.db, "commit"):
			result = server_script_api.collect_chat_turn_reply(
				self._handle(), {"response": "no row, still an answer"}
			)

		self.assertEqual(result["response"], "no row, still an answer")
		self.assertTrue(result["bpmn_driven"])

	def test_an_empty_output_and_no_message_is_still_nothing(self):
		with patch.object(frappe.db, "commit"):
			result = server_script_api.collect_chat_turn_reply(self._handle(), {"response": "   "})

		self.assertIsNone(result)
