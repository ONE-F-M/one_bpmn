# Copyright (c) 2026, one-fm and contributors
# WI-001670: the shared AG-UI event stream and the invoke_agent streaming seam.
#
# Everything here runs against mocks — no live LLM, no agent configuration
# rows are required on the site.

from __future__ import annotations

import json
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase


def _collect(gen) -> list[str]:
	return [chunk for chunk in gen]


def _events(chunks: list[str]) -> list[dict]:
	"""Parse encoded SSE lines back into event dicts (ignores comments)."""
	out = []
	for chunk in chunks:
		for line in chunk.splitlines():
			if line.startswith("data: "):
				out.append(json.loads(line[len("data: ") :]))
	return out


def _types(chunks: list[str]) -> list[str]:
	return [e.get("type") for e in _events(chunks)]


class TestAgentEventStream(FrappeTestCase):
	"""Lifecycle and payload rules of one_bpmn.agents.agui_stream."""

	def test_buffered_reply_emits_valid_lifecycle(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "hello there", "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		types = _types(chunks)
		self.assertEqual(types[0], "RUN_STARTED")
		self.assertEqual(types[-1], "RUN_FINISHED")
		self.assertIn("TEXT_MESSAGE_START", types)
		self.assertIn("TEXT_MESSAGE_CONTENT", types)
		self.assertIn("TEXT_MESSAGE_END", types)
		# content precedes the terminal event; exactly one terminal event
		self.assertEqual(types.count("RUN_FINISHED"), 1)
		self.assertEqual(types.count("RUN_ERROR"), 0)
		deltas = [e["delta"] for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_CONTENT"]
		self.assertEqual(deltas, ["hello there"])

	def test_run_started_carries_conversation_as_thread_id(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "x", "conversation": "CONV-42"},
		):
			chunks = _collect(agui_stream.agent_event_stream("a", "m", "CONV-42"))
		started = next(e for e in _events(chunks) if e.get("type") == "RUN_STARTED")
		self.assertEqual(started.get("threadId") or started.get("thread_id"), "CONV-42")

	def test_failure_emits_run_error_then_exactly_one_terminal(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			side_effect=Exception("model exploded"),
		):
			chunks = _collect(agui_stream.agent_event_stream("a", "m", "CONV-1"))
		types = _types(chunks)
		self.assertIn("RUN_ERROR", types)
		self.assertEqual(types[-1], "RUN_FINISHED")
		self.assertEqual(types.count("RUN_FINISHED"), 1)

	def test_choice_intent_becomes_onefm_choice_event(self):
		from one_bpmn.agents import agui_stream

		reply = {
			"response": "Which script do you mean?",
			"intent": "DISAMBIGUATE",
			"options": ["Onboarding Validate", "Dept Rollup"],
			"conversation": "CONV-1",
		}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=reply):
			chunks = _collect(agui_stream.agent_event_stream("logix", "m", "CONV-1"))
		customs = [e for e in _events(chunks) if e.get("type") == "CUSTOM"]
		self.assertTrue(customs, "expected a CUSTOM event for a DISAMBIGUATE reply")
		self.assertEqual(customs[0]["name"], "onefm.choice")
		self.assertEqual(customs[0]["value"]["options"], ["Onboarding Validate", "Dept Rollup"])

	def test_plain_reply_emits_no_custom_events(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "plain answer", "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("a", "m", "CONV-1"))
		self.assertEqual([e for e in _events(chunks) if e.get("type") == "CUSTOM"], [])

	def test_broken_translator_never_kills_the_stream(self):
		from one_bpmn.agents import agui_stream

		def bad_translator(result):
			raise RuntimeError("translator bug")

		agui_stream.register_extension_translator(bad_translator)
		try:
			with patch(
				"one_bpmn.api.agent_invocation.invoke_agent",
				return_value={"response": "ok", "conversation": "CONV-1"},
			):
				chunks = _collect(agui_stream.agent_event_stream("a", "m", "CONV-1"))
			types = _types(chunks)
			self.assertEqual(types[-1], "RUN_FINISHED")
			self.assertNotIn("RUN_ERROR", types)
		finally:
			agui_stream._EXTENSION_TRANSLATORS.remove(bad_translator)

	# ── Relay of a streaming (langgraph) child ──────────────────────────────

	def test_child_stream_is_relayed_with_lifecycle_owned_by_parent(self):
		from one_bpmn.agents import agui_stream

		def child():
			yield {"type": "RUN_STARTED", "run_id": "child"}          # dropped
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "to"}     # re-encoded
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "ken"}
			yield {"type": "CUSTOM", "name": "MODE_TRANSITION", "value": {"new_mode": "plan"}}
			yield {"type": "RUN_FINISHED", "run_id": "child"}         # dropped

		streaming_reply = {"streaming": True, "stream": child(), "conversation": "CONV-1"}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=streaming_reply):
			chunks = _collect(agui_stream.agent_event_stream("ba", "m", "CONV-1"))

		types = _types(chunks)
		# parent lifecycle only: the child's RUN_* copies must not appear twice
		self.assertEqual(types.count("RUN_STARTED"), 1)
		self.assertEqual(types.count("RUN_FINISHED"), 1)
		deltas = [e["delta"] for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_CONTENT"]
		self.assertEqual(deltas, ["to", "ken"])
		self.assertIn("CUSTOM", types)

	def test_flat_legacy_payload_is_folded_into_value(self):
		"""WI-001678: lumina.py yields LUCRUSHER_RESULT's payload FLAT on the
		event, not under `value` — and `value` is all the panel reads. The
		relay must fold it, or the renamed event arrives empty."""
		from one_bpmn.agents import agui_stream

		def child():
			yield {
				"type": "CUSTOM",
				"event": "LUCRUSHER_RESULT",
				"intent": "TOPOLOGY_PROPOSAL",
				"matches": [],
				"topology": {"processes": [{"name": "Onboarding"}]},
			}
			yield {"type": "CUSTOM", "event": "MODE_TRANSITION", "new_mode": "Planning"}

		streaming_reply = {"streaming": True, "stream": child(), "conversation": "CONV-1"}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=streaming_reply):
			chunks = _collect(agui_stream.agent_event_stream("lucrusher_agent", "m", "CONV-1"))

		customs = {e["name"]: e for e in _events(chunks) if e.get("type") == "CUSTOM"}
		lucrusher = customs["onefm.lucrusher_result"]
		self.assertEqual(lucrusher["value"]["intent"], "TOPOLOGY_PROPOSAL")
		self.assertEqual(lucrusher["value"]["topology"], {"processes": [{"name": "Onboarding"}]})
		# the producer's keys move INTO value — they do not also stay outside it
		self.assertNotIn("intent", lucrusher)
		self.assertNotIn("event", lucrusher)
		self.assertEqual(customs["onefm.mode_transition"]["value"], {"new_mode": "Planning"})

	def test_producer_supplied_value_survives_the_fold(self):
		"""A producer that already speaks the contract keeps its own payload."""
		from one_bpmn.agents import agui_stream

		def child():
			yield {"type": "CUSTOM", "name": "MODE_TRANSITION", "value": {"new_mode": "plan"}}

		streaming_reply = {"streaming": True, "stream": child(), "conversation": "CONV-1"}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=streaming_reply):
			chunks = _collect(agui_stream.agent_event_stream("ba", "m", "CONV-1"))

		custom = [e for e in _events(chunks) if e.get("type") == "CUSTOM"][0]
		self.assertEqual(custom["name"], "onefm.mode_transition")
		self.assertEqual(custom["value"], {"new_mode": "plan"})

	def test_child_run_error_becomes_single_parent_error(self):
		from one_bpmn.agents import agui_stream

		def child():
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "partial"}
			yield {"type": "RUN_ERROR", "message": "graph failed"}

		streaming_reply = {"streaming": True, "stream": child(), "conversation": "CONV-1"}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=streaming_reply):
			chunks = _collect(agui_stream.agent_event_stream("ba", "m", "CONV-1"))
		types = _types(chunks)
		self.assertEqual(types.count("RUN_ERROR"), 1)
		self.assertEqual(types[-1], "RUN_FINISHED")

	def test_already_encoded_lines_pass_through_untouched(self):
		from one_bpmn.agents import agui_stream

		raw = 'data: {"type": "STATE_SNAPSHOT", "snapshot": {"k": 1}}\n\n'

		def child():
			yield raw

		streaming_reply = {"streaming": True, "stream": child(), "conversation": "CONV-1"}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=streaming_reply):
			chunks = _collect(agui_stream.agent_event_stream("ba", "m", "CONV-1"))
		self.assertIn(raw, chunks)


class TestInvokeAgentStreamSeam(FrappeTestCase):
	"""The stream flag threads through invoke_agent without changing the
	buffered contract."""

	def _patched(self, runner_result, runner_key="langgraph"):
		"""Patch everything invoke_agent touches except the seam under test."""
		from one_bpmn.api import agent_invocation as ai

		class _Screened:
			text = "msg"
			enabled = False

		patches = [
			patch.object(ai, "_resolve_config", return_value={"agent_id": "x", "name": "X"}),
			patch.object(ai, "_authorize"),
			patch.object(ai, "_runner_for", return_value=runner_key),
			patch.dict(ai._RUNNERS, {runner_key: lambda c, cv, m, ctx, stream=False: runner_result(stream)}),
			patch("one_bpmn.security.pii.screen_input", return_value=_Screened()),
			patch("one_bpmn.security.pii.begin_turn", return_value=object()),
			patch("one_bpmn.security.pii.end_turn"),
		]
		return patches

	def test_stream_true_returns_generator_envelope(self):
		from one_bpmn.api import agent_invocation as ai

		def runner(stream):
			def gen():
				yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "hi"}
			return gen() if stream else {"response": "buffered"}

		patches = self._patched(runner)
		for p in patches:
			p.start()
		try:
			result = ai.invoke_agent("x", "msg", conversation="CONV-1", stream=True)
			self.assertTrue(result.get("streaming"))
			self.assertEqual(result.get("conversation"), "CONV-1")
			items = list(result["stream"])
			self.assertEqual(items[0]["delta"], "hi")
		finally:
			for p in patches:
				p.stop()

	def test_stream_false_contract_is_unchanged(self):
		from one_bpmn.api import agent_invocation as ai

		def runner(stream):
			self.assertFalse(stream)
			return {"response": "buffered"}

		patches = self._patched(runner)
		for p in patches:
			p.start()
		try:
			result = ai.invoke_agent("x", "msg", conversation="CONV-1")
			self.assertEqual(result["response"], "buffered")
			self.assertNotIn("streaming", result)
			self.assertEqual(result["conversation"], "CONV-1")
			self.assertEqual(result["agent_id"], "x")
		finally:
			for p in patches:
				p.stop()

	def test_pii_teardown_waits_for_stream_exhaustion(self):
		from one_bpmn.api import agent_invocation as ai

		def runner(stream):
			def gen():
				yield "a"
				yield "b"
			return gen()

		patches = self._patched(runner)
		for p in patches:
			p.start()
		try:
			result = ai.invoke_agent("x", "msg", conversation="CONV-1", stream=True)
			from one_bpmn.security import pii

			pii.end_turn.assert_not_called()
			list(result["stream"])  # exhaust
			pii.end_turn.assert_called_once()
		finally:
			for p in patches:
				p.stop()


class TestBpmnMapResumeRearm(FrappeTestCase):
	"""WI-001672 resume, map-driven half: a conversation whose instance has
	completed re-arms through the conditional-start gate and retries — the
	'reopen the chat' dead end fires only when re-arming genuinely fails."""

	def _invoke(self, delegate_results, rearm):
		from one_bpmn.api import agent_invocation as ai

		calls = {"delegate": 0}

		def fake_delegate(conversation, message, context=None, wait=True):
			calls["delegate"] += 1
			return delegate_results[min(calls["delegate"], len(delegate_results)) - 1]

		config = {"agent_id": "x", "name": "X", "process_model": "X — Chat"}
		with (
			patch("one_bpmn.api.server_script_api.delegate_chat_turn", side_effect=fake_delegate),
			patch("one_bpmn.one_bpmn.trigger._maybe_start_instance", side_effect=rearm) as spawn,
			patch("frappe.get_doc", return_value=object()),
		):
			from one_bpmn.api.agent_invocation import _run_bpmn_map

			try:
				result = _run_bpmn_map(config, "CONV-1", "msg", {})
			except Exception as e:
				return calls, spawn, e
			return calls, spawn, result

	def test_nothing_delivered_goes_straight_to_the_rearm(self):
		"""No settle loop any more. Delivery accepts a Queued instance and
		starts it itself, so a None here means there is no live instance to
		deliver to and retrying the same call cannot change that."""
		calls, spawn, result = self._invoke([None, {"response": "settled"}], lambda *a: None)
		self.assertEqual(result["response"], "settled")
		self.assertEqual(calls["delegate"], 2)
		spawn.assert_called_once()

	def test_dead_instance_rearms_and_retries(self):
		results = [None, {"response": "back from the dead"}]
		calls, spawn, result = self._invoke(results, lambda *a: None)
		self.assertEqual(result["response"], "back from the dead")
		self.assertEqual(calls["delegate"], 2)
		spawn.assert_called_once()

	def test_live_instance_never_rearms(self):
		calls, spawn, result = self._invoke([{"response": "fine"}], lambda *a: None)
		self.assertEqual(result["response"], "fine")
		self.assertEqual(calls["delegate"], 1)
		spawn.assert_not_called()

	def test_failed_rearm_surfaces_the_reopen_error(self):
		import frappe as _frappe

		calls, spawn, err = self._invoke([None], lambda *a: None)
		self.assertIsInstance(err, _frappe.ValidationError)
		self.assertEqual(calls["delegate"], 2)  # the first attempt, then the re-arm retry


class TestHeartbeatKeepsTheRequestContext(FrappeTestCase):
	"""The keep-alive runs the turn on another thread, which starts with an
	empty context unless the request's is carried across."""

	def test_the_callable_still_sees_the_session(self):
		import frappe

		from one_bpmn.agents import agui_stream

		seen = {}

		def _work():
			seen["user"] = frappe.session.user
			seen["in_test"] = frappe.flags.in_test
			return "done"

		gen = agui_stream._invoke_with_heartbeat(_work, interval=0.01)
		result = None
		try:
			while True:
				next(gen)
		except StopIteration as stop:
			result = stop.value

		self.assertEqual(result, "done")
		self.assertEqual(seen["user"], frappe.session.user)
		self.assertTrue(seen["in_test"])

	def test_an_exception_comes_back_to_the_caller(self):
		from one_bpmn.agents import agui_stream

		def _boom():
			raise ValueError("from the worker thread")

		gen = agui_stream._invoke_with_heartbeat(lambda: _boom(), interval=0.01)
		with self.assertRaises(ValueError):
			while True:
				next(gen)


class TestRelayKeepsASlowChildAlive(FrappeTestCase):
	"""The wait for a child's next event is where a parked turn spends its
	time, so that is where the keep-alive has to come from."""

	def test_a_silent_child_still_produces_keepalives(self):
		import time

		from ag_ui.encoder import EventEncoder

		from one_bpmn.agents import agui_stream

		def slow_child():
			time.sleep(0.25)
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "late"}

		out = list(
			agui_stream._relay_child_stream(
				slow_child(), EventEncoder(), "MSG-1", interval=0.05
			)
		)

		self.assertTrue([line for line in out if line.startswith(":")], "no keep-alive was sent")
		self.assertTrue([line for line in out if "late" in line], "the child's event was lost")

	def test_a_fast_child_sends_no_keepalive(self):
		from ag_ui.encoder import EventEncoder

		from one_bpmn.agents import agui_stream

		def fast_child():
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "now"}

		out = list(
			agui_stream._relay_child_stream(
				fast_child(), EventEncoder(), "MSG-1", interval=5
			)
		)

		self.assertEqual([line for line in out if line.startswith(":")], [])
		self.assertTrue([line for line in out if "now" in line])


class TestARelayGivesUpOnADeadTurn(FrappeTestCase):
	"""A worker killed mid-turn publishes nothing, so the wait has a ceiling:
	past it the stream says so instead of sending keep-alives for ever."""

	def test_a_child_that_never_yields_ends_with_a_system_notice(self):
		import threading

		from ag_ui.encoder import EventEncoder

		from one_bpmn.agents import agui_stream

		release = threading.Event()

		def dead_child():
			release.wait(30)  # never released within the ceiling below
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "too late"}

		try:
			out = list(
				agui_stream._relay_child_stream(
					dead_child(), EventEncoder(), "MSG-1", interval=0.05, stall_ceiling=0.2
				)
			)
		finally:
			release.set()

		events = _events(out)
		roles = [e.get("role") for e in events if e.get("type") == "TEXT_MESSAGE_START"]
		self.assertEqual(roles, ["system"])
		self.assertTrue(
			[e for e in events if "stopped responding" in (e.get("delta") or "")],
			"the stall notice never reached the client",
		)
		self.assertTrue([line for line in out if line.startswith(":")], "no keep-alive was sent")

	def test_a_slow_but_living_child_is_not_cut_off(self):
		import time

		from ag_ui.encoder import EventEncoder

		from one_bpmn.agents import agui_stream

		def slow_child():
			time.sleep(0.15)
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "made it"}

		out = list(
			agui_stream._relay_child_stream(
				slow_child(), EventEncoder(), "MSG-1", interval=0.05, stall_ceiling=5
			)
		)

		self.assertTrue([line for line in out if "made it" in line])
		self.assertEqual(
			[e for e in _events(out) if e.get("type") == "TEXT_MESSAGE_START"], []
		)




# ── WI-000406: progressive text deltas, TOOL_CALL_START/END, and the
# generated-id-until-persisted handoff ──────────────────────────────────────


class TestBufferedStreamProgressiveText(FrappeTestCase):
	"""A buffered reply's text now rides several TEXT_MESSAGE_CONTENT deltas
	instead of one, and every tool call the turn made is bracketed by
	TOOL_CALL_START/END using the tool's own name."""

	def test_long_reply_splits_into_multiple_deltas_that_reassemble(self):
		from one_bpmn.agents import agui_stream

		long_text = " ".join(f"word{i}" for i in range(60))  # well past one chunk
		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": long_text, "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		deltas = [e["delta"] for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_CONTENT"]
		self.assertGreater(len(deltas), 1, "a long reply must stream as more than one delta")
		self.assertEqual("".join(deltas), long_text, "deltas must reassemble to the exact reply")

	def test_short_reply_still_emits_exactly_one_delta(self):
		"""Backward compatible with every caller that assumed one delta per turn."""
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "hello there", "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		deltas = [e["delta"] for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_CONTENT"]
		self.assertEqual(deltas, ["hello there"])

	def test_tool_calls_bracket_with_start_and_end_events(self):
		from one_bpmn.agents import agui_stream

		reply = {
			"response": "used a tool",
			"tool_calls": [{"id": "call-1", "name": "lookup_record"}],
			"conversation": "CONV-1",
		}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=reply):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		types = _types(chunks)
		self.assertIn("TOOL_CALL_START", types)
		self.assertIn("TOOL_CALL_END", types)
		start = next(e for e in _events(chunks) if e.get("type") == "TOOL_CALL_START")
		end = next(e for e in _events(chunks) if e.get("type") == "TOOL_CALL_END")
		self.assertEqual(start.get("toolCallName") or start.get("tool_call_name"), "lookup_record")
		start_id = start.get("toolCallId") or start.get("tool_call_id")
		end_id = end.get("toolCallId") or end.get("tool_call_id")
		self.assertEqual(start_id, "call-1")
		self.assertEqual(end_id, "call-1")
		# TOOL_CALL_START/END come out before the terminal event, after content.
		self.assertLess(types.index("TOOL_CALL_START"), types.index("RUN_FINISHED"))

	def test_tool_calls_from_trace_are_also_bracketed(self):
		"""A runner that only exposes the AI Agent Run's turn trace (rather
		than a flat tool_calls list) still gets TOOL_CALL_START/END \u2014
		flattened from trace[].tool_calls (the ToolCallRecord shape)."""
		from one_bpmn.agents import agui_stream

		reply = {
			"response": "done",
			"trace": [{"role": "tool", "tool_calls": [{"name": "run_query"}]}],
			"conversation": "CONV-1",
		}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=reply):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		types = _types(chunks)
		self.assertIn("TOOL_CALL_START", types)
		self.assertIn("TOOL_CALL_END", types)
		start = next(e for e in _events(chunks) if e.get("type") == "TOOL_CALL_START")
		self.assertEqual(start.get("toolCallName") or start.get("tool_call_name"), "run_query")

	def test_no_tool_calls_emits_no_tool_events(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "plain", "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))
		types = _types(chunks)
		self.assertNotIn("TOOL_CALL_START", types)
		self.assertNotIn("TOOL_CALL_END", types)


class TestStreamedMessageIdentity(FrappeTestCase):
	"""The stream starts before the Bot Chat Message row exists: every text
	event of a streamed message must use ONE id throughout, and the
	persisted name (once known) is delivered separately rather than by
	silently swapping the id underneath already-rendered events."""

	def test_generated_id_is_stable_across_start_content_end(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "hi there", "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		events = _events(chunks)
		start = next(e for e in events if e.get("type") == "TEXT_MESSAGE_START")
		content = next(e for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT")
		end = next(e for e in events if e.get("type") == "TEXT_MESSAGE_END")

		def mid(e):
			return e.get("messageId") or e.get("message_id")

		self.assertEqual(mid(start), mid(content))
		self.assertEqual(mid(content), mid(end))

	def test_persisted_name_is_delivered_as_a_separate_event(self):
		from one_bpmn.agents import agui_stream

		reply = {
			"response": "hi there",
			"message_name": "Chat Message-00042",
			"conversation": "CONV-1",
		}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=reply):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		events = _events(chunks)
		text_start = next(e for e in events if e.get("type") == "TEXT_MESSAGE_START")
		stream_id = text_start.get("messageId") or text_start.get("message_id")
		# The stream's own generated id, not the persisted name, was used for
		# every text event \u2014 there was no Chat Message row yet when they went out.
		self.assertNotEqual(stream_id, "Chat Message-00042")

		persisted = next(
			(e for e in events if e.get("type") == "CUSTOM" and e.get("name") == "onefm.message_persisted"),
			None,
		)
		self.assertIsNotNone(persisted, "the persisted name must be delivered once known")
		self.assertEqual(persisted["value"]["message_name"], "Chat Message-00042")
		self.assertEqual(persisted["value"]["stream_id"], stream_id)

	def test_no_persisted_name_emits_no_handoff_event(self):
		"""A runner that never saved a Chat Message (e.g. direct_api chat
		before persistence, or a legacy path) must not fabricate a handoff."""
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "hi", "conversation": "CONV-1"},
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))
		names = [e.get("name") for e in _events(chunks) if e.get("type") == "CUSTOM"]
		self.assertNotIn("onefm.message_persisted", names)


class _FakeStepAdapter:
	"""Scripted step() responses, mirroring test_ai_step_loop.py's fixture,
	for exercising the on_tool_event callback in isolation."""

	def __init__(self, steps):
		self.steps = list(steps)

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		return self.steps.pop(0)


class TestStepLoopToolEventCallback(FrappeTestCase):
	"""WI-000406: on_tool_event fires start/end around every automatic tool
	the step loop actually executes."""

	def _run(self, adapter, tools, on_tool_event):
		import asyncio

		from one_bpmn.agents.executor.step_loop import run_agent_loop

		return asyncio.run(
			run_agent_loop(
				adapter,
				system="sys",
				user="do the thing",
				tools=tools,
				max_tokens=100,
				max_turns=10,
				on_tool_event=on_tool_event,
			)
		)

	def test_start_then_end_fire_around_a_successful_tool_call(self):
		from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec

		events = []
		adapter = _FakeStepAdapter([
			StepResult(
				content="checking",
				tool_calls=[StepToolCall(id="c1", name="lookup", arguments={})],
			),
			StepResult(content="answer"),
		])
		tool = ToolSpec(fn=lambda **kw: "42", name="lookup", description="look things up")

		completion, suspension = self._run(adapter, [tool], lambda phase, name: events.append((phase, name)))

		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "answer")
		self.assertEqual(events, [("start", "lookup"), ("end", "lookup")])

	def test_end_fires_even_when_the_tool_raises(self):
		from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec

		events = []

		def boom(**kw):
			raise RuntimeError("kaboom")

		adapter = _FakeStepAdapter([
			StepResult(
				content="checking",
				tool_calls=[StepToolCall(id="c1", name="breaker", arguments={})],
			),
			StepResult(content="answer"),
		])
		tool = ToolSpec(fn=boom, name="breaker", description="always fails")

		completion, suspension = self._run(adapter, [tool], lambda phase, name: events.append((phase, name)))

		self.assertIsNone(suspension)
		self.assertEqual(events, [("start", "breaker"), ("end", "breaker")])

	def test_no_events_for_a_turn_with_no_tool_calls(self):
		from one_bpmn.agents.llm_provider.base import StepResult

		events = []
		adapter = _FakeStepAdapter([StepResult(content="just an answer")])

		completion, suspension = self._run(adapter, [], lambda phase, name: events.append((phase, name)))

		self.assertIsNone(suspension)
		self.assertEqual(events, [])

	def test_broken_callback_does_not_fail_the_turn(self):
		"""A bug in the progress indicator must never break the agent's turn."""
		from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec

		def bad_callback(phase, name):
			raise RuntimeError("callback bug")

		adapter = _FakeStepAdapter([
			StepResult(
				content="checking",
				tool_calls=[StepToolCall(id="c1", name="lookup", arguments={})],
			),
			StepResult(content="answer"),
		])
		tool = ToolSpec(fn=lambda **kw: "42", name="lookup", description="look things up")

		completion, suspension = self._run(adapter, [tool], bad_callback)

		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "answer")

	def test_no_callback_at_all_is_the_unchanged_default(self):
		from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec

		adapter = _FakeStepAdapter([
			StepResult(
				content="checking",
				tool_calls=[StepToolCall(id="c1", name="lookup", arguments={})],
			),
			StepResult(content="answer"),
		])
		tool = ToolSpec(fn=lambda **kw: "42", name="lookup", description="look things up")

		completion, suspension = self._run(adapter, [tool], None)

		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "answer")
