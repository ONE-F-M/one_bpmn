# Copyright (c) 2026, one-fm and contributors
# WI-001670: the shared AG-UI event stream and the invoke_agent streaming seam.
#
# Everything here runs against mocks — no live LLM, no agent configuration
# rows are required on the site.

from __future__ import annotations

import json
import time
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


class TestInvokeWithHeartbeat(FrappeTestCase):
	"""WI-000407: the buffered turn runs on its own thread, with its own
	database connection, and keeps the SSE connection alive while it runs."""

	def _drain(self, gen):
		"""Collect every keep-alive chunk and the generator's return value."""
		chunks = []
		result = None
		try:
			while True:
				chunks.append(next(gen))
		except StopIteration as stop:
			result = stop.value
		return chunks, result

	def test_slow_call_yields_keepalive_comments_every_interval(self):
		from one_bpmn.agents import agui_stream

		def slow():
			time.sleep(0.25)
			return "done"

		gen = agui_stream._invoke_with_heartbeat(slow, interval=0.05)
		chunks, result = self._drain(gen)

		self.assertGreaterEqual(len(chunks), 2)
		self.assertTrue(all(c == ": keep-alive\n\n" for c in chunks))
		self.assertEqual(result, "done")

	def test_fast_call_sends_no_keepalive(self):
		from one_bpmn.agents import agui_stream

		gen = agui_stream._invoke_with_heartbeat(lambda: "quick", interval=1)
		chunks, result = self._drain(gen)

		self.assertEqual(chunks, [])
		self.assertEqual(result, "quick")

	def test_worker_exception_reaches_the_caller(self):
		from one_bpmn.agents import agui_stream

		def boom():
			raise ValueError("worker exploded")

		with self.assertRaises(ValueError):
			list(agui_stream._invoke_with_heartbeat(boom, interval=0.05))

	def test_stream_relays_keepalive_comments_from_a_slow_buffered_turn(self):
		"""End to end through agent_event_stream: a slow buffered runner
		still produces a valid lifecycle, with keep-alive comments relayed
		before the content."""
		from one_bpmn.agents import agui_stream

		def slow_invoke(*args, **kwargs):
			time.sleep(0.2)
			return {"response": "hello there", "conversation": "CONV-1"}

		with (
			patch("one_bpmn.api.agent_invocation.invoke_agent", side_effect=slow_invoke),
			patch.object(agui_stream, "_HEARTBEAT_SECONDS", 0.05),
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		keepalives = [c for c in chunks if c == ": keep-alive\n\n"]
		self.assertGreaterEqual(len(keepalives), 1)
		types = _types(chunks)
		self.assertEqual(types[0], "RUN_STARTED")
		self.assertEqual(types[-1], "RUN_FINISHED")
		deltas = [e["delta"] for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_CONTENT"]
		self.assertEqual(deltas, ["hello there"])


class TestRefusalRole(FrappeTestCase):
	"""WI-000407: a rate-limit refusal must not look like the agent talking."""

	def test_rate_limited_refusal_is_delivered_as_system_role(self):
		from one_bpmn.agents import agui_stream
		from one_bpmn.security.rate_limit import RateLimited

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			side_effect=RateLimited("You are sending messages too quickly."),
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		start = next(e for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_START")
		self.assertEqual(start.get("role"), "system")

	def test_other_refusal_keeps_assistant_role(self):
		from one_bpmn.agents import agui_stream
		from one_bpmn.security.refusal import AgentRefusal

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			side_effect=AgentRefusal("blocked by injection screening"),
		):
			chunks = _collect(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		start = next(e for e in _events(chunks) if e.get("type") == "TEXT_MESSAGE_START")
		self.assertEqual(start.get("role"), "assistant")


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

		def fake_delegate(conversation, message, context=None):
			calls["delegate"] += 1
			return delegate_results[min(calls["delegate"], len(delegate_results)) - 1]

		config = {"agent_id": "x", "name": "X", "process_model": "X — Chat"}
		with (
			patch("one_bpmn.api.server_script_api.delegate_chat_turn", side_effect=fake_delegate),
			patch("one_bpmn.one_bpmn.trigger._maybe_start_instance", side_effect=rearm) as spawn,
			patch("frappe.get_doc", return_value=object()),
			patch("time.sleep"),  # the first-turn settle loop must not slow tests
		):
			from one_bpmn.api.agent_invocation import _run_bpmn_map

			try:
				result = _run_bpmn_map(config, "CONV-1", "msg", {})
			except Exception as e:
				return calls, spawn, e
			return calls, spawn, result

	def test_settle_loop_recovers_a_racing_first_turn(self):
		# None once (instance still Queued mid-start), then delivered — no re-arm
		calls, spawn, result = self._invoke([None, {"response": "settled"}], lambda *a: None)
		self.assertEqual(result["response"], "settled")
		self.assertEqual(calls["delegate"], 2)
		spawn.assert_not_called()

	def test_dead_instance_rearms_and_retries(self):
		# None through the whole settle loop (1+8), then the re-arm retry lands
		results = [None] * 9 + [{"response": "back from the dead"}]
		calls, spawn, result = self._invoke(results, lambda *a: None)
		self.assertEqual(result["response"], "back from the dead")
		self.assertEqual(calls["delegate"], 10)
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
		self.assertEqual(calls["delegate"], 10)  # settle loop (1+8) + re-arm retry
