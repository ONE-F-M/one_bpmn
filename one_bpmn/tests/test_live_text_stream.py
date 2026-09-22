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


class TestTheSinkExistsOnlyForATurnInTheRequest(FrappeTestCase):
	"""A map-driven turn must not stream: its model calls include sub-agents
	whose text is for the map, and the reply is composed afterwards."""

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags["bpmn_ai_current_run"] = None
		frappe.flags["bpmn_ai_live_text_queue"] = None

	def tearDown(self):
		frappe.flags["bpmn_ai_current_run"] = None
		frappe.flags["bpmn_ai_live_text_queue"] = None

	def test_no_queue_means_no_sink(self):
		from one_bpmn.agents.turn_signal import live_text_sink

		self.assertIsNone(live_text_sink())

	def test_a_map_driven_run_with_a_chat_instance_still_gets_no_sink(self):
		from one_bpmn.agents import turn_signal

		frappe.flags["bpmn_ai_current_run"] = "RUN-2"
		with patch.object(turn_signal, "publish_event") as published:
			self.assertIsNone(turn_signal.live_text_sink())
		published.assert_not_called()


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


class TestTheSinkPublishesToTheFlaggedChatInstance(FrappeTestCase):
	"""The second live_text_sink branch: frappe.flags carries the instance the
	dispatcher marked, and every non-empty delta is published to it."""

	def tearDown(self):
		from one_bpmn.agents.turn_signal import LIVE_TEXT_INSTANCE_FLAG

		frappe.flags[LIVE_TEXT_INSTANCE_FLAG] = None

	def test_deltas_are_published_to_that_instance_and_nothing_else(self):
		from one_bpmn.agents import turn_signal

		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = "BPMN-INST-1"
		with patch.object(turn_signal, "publish_event") as published:
			sink = turn_signal.live_text_sink()
			self.assertIsNotNone(sink)
			sink("Hel")
			sink("")
			sink("lo")

		self.assertEqual(
			published.call_args_list,
			[
				(("BPMN-INST-1", {"type": "TEXT_MESSAGE_CONTENT", "delta": "Hel"}),),
				(("BPMN-INST-1", {"type": "TEXT_MESSAGE_CONTENT", "delta": "lo"}),),
			],
		)

	def test_no_flag_means_no_sink(self):
		from one_bpmn.agents import turn_signal

		self.assertIsNone(frappe.flags.get(turn_signal.LIVE_TEXT_INSTANCE_FLAG))
		self.assertIsNone(turn_signal.live_text_sink())


class TestDispatchAiAgentManagesTheLiveTextFlag(FrappeTestCase):
	"""dispatch_ai_agent (dispatchers.py): the flag is set only for a shape
	that opted in with aiStreamToReader AND only for a Chat Conversation
	instance, and it is always cleared afterwards, even on failure."""

	def _instance(self, context_doctype=None):
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"test-{frappe.generate_hash(length=6)}",
				"status": "Active",
				"context_doctype": context_doctype or "",
				"context_docname": "SOME-DOC" if context_doctype else "",
			}
		)
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)
		return instance

	def _task(self, bpmn_id="Agent_1"):
		return frappe._dict({"data": {}, "task_spec": frappe._dict({"name": bpmn_id, "description": "Agent"})})

	def _base_task_cfg(self, **extra):
		return {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "hi",
			"aiOutputVariable": "agent_out",
			**extra,
		}

	def tearDown(self):
		frappe.flags["bpmn_ai_live_text_instance"] = None

	def test_flag_set_only_when_opted_in_and_chat_conversation(self):
		from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		instance = self._instance(context_doctype="Chat Conversation")
		task = self._task()
		task_cfg = self._base_task_cfg(aiStreamToReader="1")
		seen = {}

		def fake_run(_self, config, context):
			seen["flag_during_call"] = frappe.flags.get("bpmn_ai_live_text_instance")
			return ExecutorResult(
				output="hi", error_code=ErrorCode.SUCCESS,
				token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
			)

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(instance, task, task_cfg, "Agent_1")

		self.assertEqual(seen["flag_during_call"], instance.name)
		self.assertIsNone(frappe.flags.get("bpmn_ai_live_text_instance"))

	def test_flag_not_set_without_the_attribute(self):
		from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		instance = self._instance(context_doctype="Chat Conversation")
		task = self._task()
		task_cfg = self._base_task_cfg()  # no aiStreamToReader
		seen = {}

		def fake_run(_self, config, context):
			seen["flag_during_call"] = frappe.flags.get("bpmn_ai_live_text_instance")
			return ExecutorResult(
				output="hi", error_code=ErrorCode.SUCCESS,
				token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
			)

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(instance, task, task_cfg, "Agent_1")

		self.assertIsNone(seen["flag_during_call"])
		self.assertIsNone(frappe.flags.get("bpmn_ai_live_text_instance"))

	def test_flag_not_set_for_a_non_chat_instance(self):
		from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		instance = self._instance(context_doctype="Task")  # not Chat Conversation
		task = self._task()
		task_cfg = self._base_task_cfg(aiStreamToReader="1")
		seen = {}

		def fake_run(_self, config, context):
			seen["flag_during_call"] = frappe.flags.get("bpmn_ai_live_text_instance")
			return ExecutorResult(
				output="hi", error_code=ErrorCode.SUCCESS,
				token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
			)

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(instance, task, task_cfg, "Agent_1")

		self.assertIsNone(seen["flag_during_call"])

	def test_flag_cleared_even_when_the_executor_raises(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		instance = self._instance(context_doctype="Chat Conversation")
		task = self._task()
		task_cfg = self._base_task_cfg(aiStreamToReader="1")

		def fake_run(_self, config, context):
			raise RuntimeError("provider down")

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			# dispatch_ai_agent swallows executor exceptions and records them
			# on task.data rather than propagating \u2014 the flag must still be
			# cleared on that path.
			dispatchers.dispatch_ai_agent(instance, task, task_cfg, "Agent_1")

		self.assertIsNone(frappe.flags.get("bpmn_ai_live_text_instance"))
