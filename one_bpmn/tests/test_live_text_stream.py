# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Model text reaches the chat reader while the model is still writing.

bench run-tests --skip-before-tests --module one_bpmn.tests.test_live_text_stream
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


def _events(chunks):
	out = []
	for chunk in chunks:
		for line in str(chunk).split("\n"):
			if line.startswith("data:"):
				try:
					out.append(json.loads(line[5:].strip()))
				except ValueError:
					pass
	return out


class _FakeStream:
	"""Just enough of the SDK's MessageStream: iterable events, then a final message."""

	def __init__(self, events):
		self._events = events

	def __aiter__(self):
		async def gen():
			for e in self._events:
				yield e
		return gen()


class TestTheAdapterForwardsTextAsItArrives(FrappeTestCase):
	def _run(self, events, sink):
		from one_bpmn.agents.llm_provider import anthropic_adapter

		with patch.object(anthropic_adapter, "live_text_sink", create=True):
			with patch("one_bpmn.agents.turn_signal.live_text_sink", return_value=sink):
				asyncio.run(anthropic_adapter._forward_text(_FakeStream(events)))

	def test_each_text_event_reaches_the_sink_in_order(self):
		got = []
		self._run(
			[
				SimpleNamespace(type="text", text="Hel"),
				SimpleNamespace(type="content_block_stop"),
				SimpleNamespace(type="text", text="lo"),
				SimpleNamespace(type="text", text=""),
			],
			got.append,
		)
		self.assertEqual(got, ["Hel", "lo"])

	def test_no_sink_means_the_stream_is_left_untouched(self):
		consumed = []

		class Watching(_FakeStream):
			def __aiter__(self):
				consumed.append(True)
				return super().__aiter__()

		from one_bpmn.agents.llm_provider import anthropic_adapter

		with patch("one_bpmn.agents.turn_signal.live_text_sink", return_value=None):
			asyncio.run(anthropic_adapter._forward_text(Watching([SimpleNamespace(type="text", text="x")])))
		self.assertEqual(consumed, [], "with nobody waiting the adapter must not read ahead")

	def test_a_failing_sink_never_fails_the_call(self):
		def boom(delta):
			raise RuntimeError("redis is down")

		self._run([SimpleNamespace(type="text", text="a")], boom)  # must not raise


class TestTheSinkExistsForARequestOrANamedInstance(FrappeTestCase):
	"""A turn in the request gets a queue. A turn on the worker gets one when
	the dispatcher names the conversation's instance. A tool call masks both."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._reset()

	def tearDown(self):
		self._reset()

	def _reset(self):
		from one_bpmn.agents import turn_signal

		for flag in (
			"bpmn_ai_current_run",
			turn_signal.LIVE_TEXT_QUEUE_FLAG,
			turn_signal.LIVE_TEXT_INSTANCE_FLAG,
			turn_signal.LIVE_TEXT_MASK_FLAG,
		):
			frappe.flags[flag] = None

	def test_no_queue_and_no_instance_means_no_sink(self):
		from one_bpmn.agents.turn_signal import live_text_sink

		frappe.flags["bpmn_ai_current_run"] = "RUN-2"
		self.assertIsNone(live_text_sink())

	def test_a_named_instance_publishes_each_delta_as_a_text_event(self):
		from one_bpmn.agents import turn_signal

		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = "INST-1"
		with patch.object(turn_signal, "publish_event") as published:
			sink = turn_signal.live_text_sink()
			self.assertIsNotNone(sink)
			sink("Hel"); sink(""); sink("lo")
		self.assertEqual(
			[c.args for c in published.call_args_list],
			[("INST-1", {"type": "TEXT_MESSAGE_CONTENT", "delta": "Hel"}), ("INST-1", {"type": "TEXT_MESSAGE_CONTENT", "delta": "lo"})],
		)

	def test_a_masked_instance_gets_no_sink_and_the_mask_lifts_afterwards(self):
		from one_bpmn.agents import turn_signal

		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = "INST-1"
		with turn_signal.mask_live_text():
			self.assertIsNone(turn_signal.live_text_sink())
			with turn_signal.mask_live_text():
				self.assertIsNone(turn_signal.live_text_sink())
			self.assertIsNone(turn_signal.live_text_sink(), "an inner mask must not lift the outer one")
		self.assertIsNotNone(turn_signal.live_text_sink())

	def test_the_scope_names_only_a_conversation_instance(self):
		from one_bpmn.agents import turn_signal

		chat = SimpleNamespace(name="INST-CHAT", context_doctype="Chat Conversation")
		background = SimpleNamespace(name="INST-BG", context_doctype="Work Item")
		with turn_signal.live_text_scope(background):
			self.assertIsNone(frappe.flags.get(turn_signal.LIVE_TEXT_INSTANCE_FLAG))
		with turn_signal.live_text_scope(chat):
			self.assertEqual(frappe.flags.get(turn_signal.LIVE_TEXT_INSTANCE_FLAG), "INST-CHAT")
		self.assertIsNone(frappe.flags.get(turn_signal.LIVE_TEXT_INSTANCE_FLAG))

	def test_a_shape_tool_runs_masked_and_still_reports_its_end(self):
		from one_bpmn.agents import shape_tools, turn_signal

		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = "INST-1"
		seen = {}

		def body(instance, bpmn_id, task_cfg, kwargs):
			seen["sink"] = turn_signal.live_text_sink()
			return "{}"

		instance = SimpleNamespace(name="INST-1", context_doctype="Chat Conversation")
		with patch.object(shape_tools, "_execute_shape_body", side_effect=body), patch.object(
			shape_tools, "_announce"
		) as announced:
			shape_tools.execute_shape(instance, "lookup", {}, {})
		self.assertIsNone(seen["sink"])
		self.assertIsNotNone(turn_signal.live_text_sink())
		self.assertEqual([c.args[1] for c in announced.call_args_list], ["TOOL_CALL_START", "TOOL_CALL_END"])


class TestTheRelayOpensTheReplyOnTheFirstLiveDelta(FrappeTestCase):
	def _relay(self, child_events, state):
		from ag_ui.encoder import EventEncoder

		from one_bpmn.agents import agui_stream

		return list(agui_stream._relay_child_stream(iter(child_events), EventEncoder(), "MSG-1", interval=5, state=state))

	def test_start_is_sent_once_and_the_state_remembers_it(self):
		state = {}
		out = self._relay(
			[{"type": "TEXT_MESSAGE_CONTENT", "delta": "Hel"}, {"type": "TEXT_MESSAGE_CONTENT", "delta": "lo"}],
			state,
		)
		types = [e["type"] for e in _events(out)]
		self.assertEqual(types, ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_CONTENT"])
		self.assertTrue(state.get("text_streamed"))

	def test_no_live_text_leaves_the_state_alone(self):
		state = {}
		out = self._relay([{"type": "TOOL_CALL_START", "toolCallName": "lookup"}], state)
		self.assertNotIn("TEXT_MESSAGE_START", [e["type"] for e in _events(out)])
		self.assertFalse(state.get("text_streamed"))

	def test_without_a_state_the_relay_behaves_as_before(self):
		out = self._relay([{"type": "TEXT_MESSAGE_CONTENT", "delta": "x"}], None)
		self.assertEqual([e["type"] for e in _events(out)], ["TEXT_MESSAGE_CONTENT"])

	def test_a_tool_call_closes_the_words_before_it_and_the_reply_reopens(self):
		state = {}
		out = self._relay(
			[
				{"type": "TEXT_MESSAGE_CONTENT", "delta": "Let me look."},
				{"type": "TOOL_CALL_START", "toolCallName": "lookup"},
				{"type": "TOOL_CALL_END", "toolCallName": "lookup"},
				{"type": "TEXT_MESSAGE_CONTENT", "delta": "Found "},
				{"type": "TEXT_MESSAGE_CONTENT", "delta": "it."},
			],
			state,
		)
		types = [e["type"] for e in _events(out)]
		self.assertEqual(
			types,
			[
				"TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
				"TOOL_CALL_START", "TOOL_CALL_END",
				"TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_CONTENT",
			],
		)
		self.assertTrue(state["text_streamed"])
		self.assertEqual(state["streamed_text"], "Found it.")

	def test_a_tool_call_with_no_words_before_it_closes_nothing(self):
		state = {}
		out = self._relay([{"type": "TOOL_CALL_START", "toolCallName": "lookup"}], state)
		self.assertEqual([e["type"] for e in _events(out)], ["TOOL_CALL_START"])


class TestTheBufferedPathDoesNotResendStreamedText(FrappeTestCase):
	def _stream(self, result):
		from one_bpmn.agents import agui_stream

		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=result):
			return list(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

	def test_streamed_text_gets_only_an_end(self):
		out = self._stream({
			"response": "already on screen", "conversation": "CONV-1",
			"text_streamed": True, "streamed_text": "already  on screen",
		})
		types = [e["type"] for e in _events(out)]
		self.assertNotIn("TEXT_MESSAGE_CONTENT", types)
		self.assertNotIn("TEXT_MESSAGE_START", types)
		self.assertEqual(types.count("TEXT_MESSAGE_END"), 1)

	def test_a_reply_composed_after_the_words_is_sent_after_them(self):
		out = self._stream({
			"response": "Connection test complete.", "conversation": "CONV-1",
			"text_streamed": True, "streamed_text": "Running the probe now.",
		})
		types = [e["type"] for e in _events(out)]
		self.assertLess(types.index("TEXT_MESSAGE_END"), types.index("TEXT_MESSAGE_START"), "the streamed words are closed first")
		self.assertEqual(types.count("TEXT_MESSAGE_START"), 1)
		self.assertEqual(
			"".join(e["delta"] for e in _events(out) if e["type"] == "TEXT_MESSAGE_CONTENT"),
			"Connection test complete.",
		)
		self.assertEqual(types.count("TEXT_MESSAGE_END"), 2)

	def test_nothing_streamed_before_the_handover_sends_the_reply_once(self):
		out = self._stream({"response": "The answer.", "conversation": "CONV-1", "text_streamed": True, "streamed_text": ""})
		types = [e["type"] for e in _events(out)]
		self.assertEqual(types.count("TEXT_MESSAGE_START"), 1)
		self.assertEqual(types.count("TEXT_MESSAGE_END"), 2)

	def test_buffered_text_still_arrives_in_chunks(self):
		out = self._stream({"response": "never streamed", "conversation": "CONV-1"})
		types = [e["type"] for e in _events(out)]
		self.assertEqual(types.count("TEXT_MESSAGE_START"), 1)
		self.assertGreaterEqual(types.count("TEXT_MESSAGE_CONTENT"), 1)
		self.assertEqual("".join(e["delta"] for e in _events(out) if e["type"] == "TEXT_MESSAGE_CONTENT"), "never streamed")


class TestADirectTurnStreamsFromTheRequest(FrappeTestCase):
	"""A turn with no instance runs inside the request, so the adapter is
	handed a queue instead of a list to publish on."""

	def tearDown(self):
		from one_bpmn.agents.turn_signal import LIVE_TEXT_QUEUE_FLAG

		frappe.flags[LIVE_TEXT_QUEUE_FLAG] = None

	def test_the_sink_prefers_the_request_queue_over_the_run(self):
		import queue

		from one_bpmn.agents import turn_signal

		q = queue.Queue()
		frappe.flags[turn_signal.LIVE_TEXT_QUEUE_FLAG] = q
		sink = turn_signal.live_text_sink()
		self.assertIsNotNone(sink)
		sink("Hel"); sink(""); sink("lo")
		self.assertEqual([q.get_nowait(), q.get_nowait()], ["Hel", "lo"])
		self.assertTrue(q.empty())

	def test_the_stream_yields_deltas_then_the_handover(self):
		from one_bpmn.agents.agui_stream import HANDOVER_EVENT
		from one_bpmn.api import agent_invocation
		from one_bpmn.agents.turn_signal import LIVE_TEXT_QUEUE_FLAG

		def fake_turn(config, conversation, message):
			sink_q = frappe.flags.get(LIVE_TEXT_QUEUE_FLAG)
			sink_q.put("The "); sink_q.put("answer.")
			return {"response": "The answer."}

		with patch.object(agent_invocation, "_direct_api_turn", side_effect=fake_turn):
			out = list(agent_invocation._stream_direct_api({}, "CONV-1", "hi", {}))

		self.assertEqual(out[:2], [
			{"type": "TEXT_MESSAGE_CONTENT", "delta": "The "},
			{"type": "TEXT_MESSAGE_CONTENT", "delta": "answer."},
		])
		self.assertEqual(out[2]["type"], HANDOVER_EVENT)
		self.assertEqual(out[2]["result"], {"response": "The answer."})
		self.assertIsNone(frappe.flags.get(LIVE_TEXT_QUEUE_FLAG), "the queue must not leak into the next turn")

	def test_a_failing_turn_raises_on_the_request_thread(self):
		from one_bpmn.api import agent_invocation

		with patch.object(agent_invocation, "_direct_api_turn", side_effect=RuntimeError("provider down")):
			with self.assertRaises(RuntimeError):
				list(agent_invocation._stream_direct_api({}, "CONV-1", "hi", {}))

	def test_without_stream_the_runner_is_unchanged(self):
		from one_bpmn.api import agent_invocation

		with patch.object(agent_invocation, "_direct_api_turn", return_value={"response": "plain"}) as turn:
			self.assertEqual(agent_invocation._run_direct_api({}, "CONV-1", "hi", {}, stream=False), {"response": "plain"})
		turn.assert_called_once()
