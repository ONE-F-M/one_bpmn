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


class TestTheSinkOnlyExistsForAChatTurn(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags["bpmn_ai_current_run"] = None

	def tearDown(self):
		frappe.flags["bpmn_ai_current_run"] = None

	def test_no_current_run_means_no_sink(self):
		from one_bpmn.agents.turn_signal import live_text_sink

		self.assertIsNone(live_text_sink())

	def test_a_background_instance_gets_no_sink(self):
		from one_bpmn.agents import turn_signal

		frappe.flags["bpmn_ai_current_run"] = "RUN-1"
		values = {("AI Agent Run", "RUN-1", "instance"): "INST-1",
		          ("BPMN Process Instance", "INST-1", "context_doctype"): "A2A Task"}
		with patch.object(turn_signal.frappe.db, "get_value", side_effect=lambda d, n, f: values.get((d, n, f))):
			self.assertIsNone(turn_signal.live_text_sink())

	def test_a_chat_instance_publishes_each_delta(self):
		from one_bpmn.agents import turn_signal

		frappe.flags["bpmn_ai_current_run"] = "RUN-2"
		values = {("AI Agent Run", "RUN-2", "instance"): "INST-2",
		          ("BPMN Process Instance", "INST-2", "context_doctype"): "Chat Conversation"}
		published = []
		with patch.object(turn_signal.frappe.db, "get_value", side_effect=lambda d, n, f: values.get((d, n, f))):
			with patch.object(turn_signal, "publish_event", side_effect=lambda i, e: published.append((i, e))):
				sink = turn_signal.live_text_sink()
				self.assertIsNotNone(sink)
				sink("Hello")
				sink("")
				sink(" there")
		self.assertEqual(published, [
			("INST-2", {"type": "TEXT_MESSAGE_CONTENT", "delta": "Hello"}),
			("INST-2", {"type": "TEXT_MESSAGE_CONTENT", "delta": " there"}),
		])


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


class TestTheBufferedPathDoesNotResendStreamedText(FrappeTestCase):
	def _stream(self, result):
		from one_bpmn.agents import agui_stream

		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=result):
			return list(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

	def test_streamed_text_gets_only_an_end(self):
		out = self._stream({"response": "already on screen", "conversation": "CONV-1", "text_streamed": True})
		types = [e["type"] for e in _events(out)]
		self.assertNotIn("TEXT_MESSAGE_CONTENT", types)
		self.assertNotIn("TEXT_MESSAGE_START", types)
		self.assertIn("TEXT_MESSAGE_END", types)

	def test_buffered_text_still_arrives_in_chunks(self):
		out = self._stream({"response": "never streamed", "conversation": "CONV-1"})
		types = [e["type"] for e in _events(out)]
		self.assertEqual(types.count("TEXT_MESSAGE_START"), 1)
		self.assertGreaterEqual(types.count("TEXT_MESSAGE_CONTENT"), 1)
		self.assertEqual("".join(e["delta"] for e in _events(out) if e["type"] == "TEXT_MESSAGE_CONTENT"), "never streamed")
