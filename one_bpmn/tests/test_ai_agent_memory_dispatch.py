# Copyright (c) 2026, one-fm and contributors
# Tests for the dispatcher memory wiring (mocked executor): disabled = no
# change, long-term memory search + injection, auto-write with source_run,
# empty search = no injection, and the executor messages slot.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
	ErrorCode,
	Executor,
	ExecutorConfig,
	ExecutorResult,
	TokenUsage,
	register_executor,
)
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D

_CAPTURED = {}


class _FakeExecutor(Executor):
	def run(self, config, context):
		_CAPTURED["config"] = config
		return ExecutorResult(
			output="agent output", token_usage=TokenUsage(1, 2, 3), error_code=ErrorCode.SUCCESS
		)


register_executor("faketest", _FakeExecutor)


def _instance():
	return SimpleNamespace(
		name="INST-X", context_doctype="", context_docname="", process_model="", initiated_by="Administrator"
	)


def _task(bpmn="Act_1"):
	return SimpleNamespace(data={}, task_spec=SimpleNamespace(bpmn_id=bpmn, name=bpmn))


class TestDispatcherMemory(FrappeTestCase):
	def setUp(self):
		_CAPTURED.clear()
		# Isolate the dispatcher from observability DB writes; return a non-stub
		# run so source_run is set. Neutralise the label lookup and the commit
		# the observability block performs (keeps FrappeTestCase rollback intact).
		patches = [
			patch(
				"one_bpmn.agents.observability.create_ai_run",
				return_value=SimpleNamespace(name="RUN-FAKE", stub=False),
			),
			patch("one_bpmn.agents.observability.record_ai_step"),
			patch("one_bpmn.agents.observability.finalize_ai_run"),
			patch("one_bpmn.agents.observability.finalize_ai_run_on_exception"),
			patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task"),
			patch("frappe.db.commit"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_disabled_no_injection_no_write(self):
		with patch("one_bpmn.agents.memory.tools.memory_search") as ms, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_instance(), _task(), {"aiBackend": "faketest", "aiSystemPrompt": "SYS", "aiUserPrompt": "U"}, "Act_1"
			)
		ms.assert_not_called()
		mw.assert_not_called()
		self.assertEqual(_CAPTURED["config"].system_prompt, "SYS")
		self.assertEqual(_CAPTURED["config"].messages, [])

	def test_long_term_memory_search_and_injection(self):
		with patch(
			"one_bpmn.agents.memory.tools.memory_search", return_value=[{"content": "net-30 rule"}]
		) as ms, patch("one_bpmn.agents.memory.tools.memory_write"):
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_9"),
				{
					"aiBackend": "faketest",
					"aiLongTermMemory": "enabled",
					"aiMemoryScope": "Agent",
					"aiSystemPrompt": "SYS",
					"aiUserPrompt": "handle order",
				},
				"Act_9",
			)
		ms.assert_called_once()
		args, _ = ms.call_args
		self.assertEqual(args[0], "Agent")   # scope
		self.assertEqual(args[1], "Act_9")   # scope key defaults to bpmn_id
		# WI-001639: retrieved memory is DYNAMIC (it is searched per turn with
		# the current user prompt), so it goes into the user message, ahead of
		# the user's text — never onto the frozen system prompt.
		self.assertEqual(_CAPTURED["config"].system_prompt, "SYS")
		up = _CAPTURED["config"].user_prompt
		self.assertIn("Relevant memory:", up)
		self.assertIn("net-30 rule", up)
		self.assertLess(up.index("Relevant memory:"), up.index("handle order"))

	def test_empty_search_no_injection(self):
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]), patch(
			"one_bpmn.agents.memory.tools.memory_write"
		):
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_E"),
				{
					"aiBackend": "faketest",
					"aiLongTermMemory": "1",
					"aiMemoryScope": "Agent",
					"aiSystemPrompt": "SYS",
					"aiUserPrompt": "q",
				},
				"Act_E",
			)
		self.assertEqual(_CAPTURED["config"].system_prompt, "SYS")
		self.assertNotIn("Relevant memory:", _CAPTURED["config"].system_prompt)
		# Nothing found — the user prompt is untouched, no marker introduced.
		self.assertEqual(_CAPTURED["config"].user_prompt, "q")

	def test_raw_write_mode_stores_output_verbatim(self):
		with patch("one_bpmn.agents.memory.tools.memory_write") as mw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_W"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "raw",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_W",
			)
		mw.assert_called_once()
		args, kwargs = mw.call_args
		self.assertEqual(args[0], "Agent")
		self.assertEqual(args[1], "Act_W")
		self.assertEqual(args[2], "agent output")          # content = output verbatim
		self.assertEqual(kwargs.get("source_run"), "RUN-FAKE")

	def test_distilled_write_mode_enqueues_distillation(self):
		# distilled is the new default path: the raw output is NOT stored; a
		# distill job is dispatched instead (run inline under tests).
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_D"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "distilled",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_D",
			)
		mw.assert_not_called()
		dw.assert_called_once()
		kwargs = dw.call_args.kwargs
		self.assertEqual(kwargs["scope"], "Agent")
		self.assertEqual(kwargs["scope_key"], "Act_D")
		self.assertEqual(kwargs["agent_output"], "agent output")
		self.assertEqual(kwargs["source_run"], "RUN-FAKE")
		self.assertEqual(kwargs["backend"], "faketest")

	def test_distilled_write_mode_passes_exclude_context(self):
		# WI-002165: the dispatch-thread system prompt (the agent's own
		# instructions for this run) is handed to the distiller so it can
		# reject a fact that just restates them.
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		):
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_X"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "distilled",
					"aiMemoryScope": "Agent",
					"aiSystemPrompt": "HARD PIPELINE RULES: always call classify_intent first.",
					"aiUserPrompt": "q",
				},
				"Act_X",
			)
		kwargs = dw.call_args.kwargs
		self.assertIn("HARD PIPELINE RULES", kwargs["exclude_context"])

	def test_distilled_tool_protocol_fallback_uses_plain_user_text_not_driving_prompt(self):
		# WI-002165 regression: a tool-protocol agent (empty result.output,
		# answer lives in the trace) used to splice the FULLY ASSEMBLED
		# user_prompt — the operator-authored driving template, e.g. Logix's
		# "HARD PIPELINE RULES" — into distillation labelled "[User message]".
		# That produced jrrd68247k/joal5ugdks: the driving template re-stored
		# as if it were something the person said. The fallback must use only
		# the person's own words (_turn_user_message), never the template.
		instance = SimpleNamespace(
			name="INST-T",
			context_doctype="Chat Conversation",
			context_docname="CONV-1",
			process_model="",
			initiated_by="Administrator",
		)
		task = SimpleNamespace(
			data={"user_text": "please handle my request"},
			task_spec=SimpleNamespace(bpmn_id="Act_T", name="Act_T"),
		)

		class _ToolProtocolExecutor(Executor):
			def run(self, config, context):
				_CAPTURED["config"] = config
				return ExecutorResult(
					output="",  # tool-protocol agent: nothing outside tool calls
					token_usage=TokenUsage(1, 2, 3),
					error_code=ErrorCode.SUCCESS,
					trace=[{"tool_calls": [{"name": "finalize", "arguments": {}, "result": "done"}]}],
				)

		register_executor("toolprotocoltest", _ToolProtocolExecutor)

		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		):
			D.dispatch_ai_agent(
				instance,
				task,
				{
					"aiBackend": "toolprotocoltest",
					"aiMemoryWriteMode": "distilled",
					"aiMemoryScope": "Agent",
					# Static driving template (never contains the real per-turn
					# message — that's appended separately below by
					# build_dynamic_preamble, same as the real Logix map).
					"aiUserPrompt": (
						"HARD PIPELINE RULES: (1) ALWAYS call classify_intent first. "
						"(2) Every turn MUST end by calling finalize."
					),
				},
				"Act_T",
			)
		agent_output = dw.call_args.kwargs["agent_output"]
		self.assertIn("please handle my request", agent_output)
		self.assertNotIn("HARD PIPELINE RULES", agent_output)
		self.assertNotIn("classify_intent", agent_output)

	def test_legacy_autowrite_defaults_to_distilled(self):
		# Back-compat: an existing element with aiMemoryAutoWrite on and no mode
		# now distils rather than dumping the reply verbatim.
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_L"),
				{
					"aiBackend": "faketest",
					"aiMemoryAutoWrite": "enabled",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_L",
			)
		dw.assert_called_once()

	def test_write_mode_off_writes_nothing(self):
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_O"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "off",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_O",
			)
		dw.assert_not_called()
		mw.assert_not_called()


def _chat_task(bpmn="Act_R", user_text="q"):
	return SimpleNamespace(
		data={"user_text": user_text}, task_spec=SimpleNamespace(bpmn_id=bpmn, name=bpmn)
	)


class TestRememberDirectiveWrite(FrappeTestCase):
	"""An explicit "remember that..." must be stored verbatim, tagged
	user_directed, bypassing the raw/distilled branches entirely — and only
	when memory writes aren't disabled outright (no separate bypass for a
	write_mode="off" agent)."""

	def setUp(self):
		_CAPTURED.clear()
		patches = [
			patch(
				"one_bpmn.agents.observability.create_ai_run",
				return_value=SimpleNamespace(name="RUN-FAKE", stub=False),
			),
			patch("one_bpmn.agents.observability.record_ai_step"),
			patch("one_bpmn.agents.observability.finalize_ai_run"),
			patch("one_bpmn.agents.observability.finalize_ai_run_on_exception"),
			patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task"),
			patch("frappe.db.commit"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_remember_directive_writes_verbatim_and_skips_distill(self):
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_chat_instance("CONV-R1"),
				_chat_task("Act_R", "Remember that every form we build needs a Site link field."),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "distilled",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_R",
			)
		dw.assert_not_called()
		mw.assert_called_once()
		args, kwargs = mw.call_args
		self.assertEqual(args[0], "Agent")
		self.assertEqual(args[1], "Act_R")
		self.assertEqual(args[2], "Remember that every form we build needs a Site link field.")
		self.assertEqual(kwargs.get("source_run"), "RUN-FAKE")
		self.assertTrue(kwargs.get("user_directed"))

	def test_remember_directive_still_bypasses_raw_mode(self):
		# The directive text is stored, not the agent's raw output.
		with patch("one_bpmn.agents.memory.tools.memory_write") as mw:
			D.dispatch_ai_agent(
				_chat_instance("CONV-R2"),
				_chat_task("Act_R2", "From now on, always cc compliance on GRD emails."),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "raw",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_R2",
			)
		args, kwargs = mw.call_args
		self.assertEqual(args[2], "From now on, always cc compliance on GRD emails.")
		self.assertTrue(kwargs.get("user_directed"))

	def test_remember_directive_writes_nothing_when_memory_disabled(self):
		# Memory disabled means disabled — no separate bypass for an explicit
		# directive when aiMemoryWriteMode is "off".
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_chat_instance("CONV-R3"),
				_chat_task("Act_R3", "Remember that every form we build needs a Site link field."),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "off",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_R3",
			)
		dw.assert_not_called()
		mw.assert_not_called()

	def test_non_directive_message_still_uses_distilled_path(self):
		# Regression: a present, non-remember user_message must not accidentally
		# trip the new branch.
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_chat_instance("CONV-R4"),
				_chat_task("Act_R4", "Add a status field to the leave request form."),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "distilled",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_R4",
			)
		mw.assert_not_called()
		dw.assert_called_once()


class TestExecutorMessagesSlot(FrappeTestCase):
	def test_openai_empty_is_system_then_user(self):
		_, payload, _ = DirectApiExecutor()._build_openai_request(
			"http://x", "k", "m", ExecutorConfig(system_prompt="S", user_prompt="U"), "Other"
		)
		self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])

	def test_openai_history_precedes_user(self):
		cfg = ExecutorConfig(system_prompt="S", user_prompt="U", messages=[{"role": "assistant", "content": "prior"}])
		_, payload, _ = DirectApiExecutor()._build_openai_request("http://x", "k", "m", cfg, "Other")
		self.assertEqual([m["role"] for m in payload["messages"]], ["system", "assistant", "user"])

	def test_anthropic_history_and_empty(self):
		ex = DirectApiExecutor()
		cfg = ExecutorConfig(system_prompt="S", user_prompt="U", messages=[{"role": "assistant", "content": "prior"}])
		_, payload, _ = ex._build_anthropic_request("http://x", "k", "m", cfg)
		self.assertEqual([m["role"] for m in payload["messages"]], ["assistant", "user"])
		# System is sent as a content block carrying a prompt-cache marker.
		self.assertEqual(
			payload.get("system"),
			[{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}],
		)
		# The last history message carries the conversation-prefix cache marker;
		# the caller's dict is never mutated.
		self.assertEqual(
			payload["messages"][0]["content"][-1]["cache_control"],
			{"type": "ephemeral"},
		)
		self.assertEqual(cfg.messages, [{"role": "assistant", "content": "prior"}])
		_, empty, _ = ex._build_anthropic_request(
			"http://x", "k", "m", ExecutorConfig(system_prompt="S", user_prompt="U")
		)
		self.assertEqual([m["role"] for m in empty["messages"]], ["user"])


def _chat_instance(conversation="CONV-1"):
	return SimpleNamespace(
		name="INST-CHAT",
		context_doctype="Chat Conversation",
		context_docname=conversation,
		process_model="",
		initiated_by="Administrator",
	)


class TestTheUserMessageReachesTheModel(FrappeTestCase):
	"""The person's own words belong in the prompt, and therefore in the step.

	A chat map used to keep them in the turn store for its tools to read, so
	every request produced a byte-identical user step and the model answered a
	constant. Two runs asking for different things were indistinguishable
	afterwards.
	"""

	def setUp(self):
		_CAPTURED.clear()
		patches = [
			patch(
				"one_bpmn.agents.observability.create_ai_run",
				return_value=SimpleNamespace(name="RUN-FAKE", stub=False),
			),
			patch("one_bpmn.agents.observability.record_ai_step"),
			patch("one_bpmn.agents.observability.finalize_ai_run"),
			patch("one_bpmn.agents.observability.finalize_ai_run_on_exception"),
			patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task"),
			patch("frappe.db.commit"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def _dispatch(self, instance, task_data=None, **cfg):
		task = SimpleNamespace(
			data=dict(task_data or {}), task_spec=SimpleNamespace(bpmn_id="Act_1", name="Act_1")
		)
		config = {"aiBackend": "faketest", "aiSystemPrompt": "SYS", "aiUserPrompt": "Process the latest message."}
		config.update(cfg)
		D.dispatch_ai_agent(instance, task, config, "Act_1")
		return _CAPTURED["config"].user_prompt

	def test_the_message_is_in_the_prompt(self):
		prompt = self._dispatch(_chat_instance(), {"user_text": "add a status field"})

		self.assertIn("add a status field", prompt)
		self.assertIn("Process the latest message.", prompt)

	def test_the_marker_sits_before_the_message_not_the_instructions(self):
		"""The adapter splits on the marker to cache everything before it. The
		instructions are the same every turn; only the message varies, so the
		split has to fall between them."""
		import re

		prompt = self._dispatch(_chat_instance(), {"user_text": "add a status field"})
		match = re.search(
			r"(\n+(?:User message|User request|User prompt|Request):\s*)(.*)$",
			prompt,
			re.IGNORECASE | re.DOTALL,
		)

		self.assertIsNotNone(match)
		self.assertEqual(match.group(2).strip(), "add a status field")
		self.assertIn("Process the latest message.", prompt[: match.start()])

	def test_two_requests_do_not_produce_the_same_prompt(self):
		"""The defect, stated as a test: identical user steps for different asks."""
		first = self._dispatch(_chat_instance(), {"user_text": "add a status field"})
		second = self._dispatch(_chat_instance(), {"user_text": "delete the invoice table"})

		self.assertNotEqual(first, second)

	def test_a_map_that_renders_the_message_itself_gets_no_second_copy(self):
		prompt = self._dispatch(
			_chat_instance(),
			{"user_text": "add a status field"},
			aiUserPrompt="Latest user message: {{ user_text }}",
		)

		self.assertEqual(prompt.count("add a status field"), 1)

	def test_the_turn_store_is_read_when_the_task_does_not_carry_it(self):
		"""ProsAlly and Logix seed the store and pass nothing down the task."""
		with patch(
			"one_bpmn.agents.turn_state.get_turn", return_value={"user_text": "draw an onboarding process"}
		):
			prompt = self._dispatch(_chat_instance())

		self.assertIn("draw an onboarding process", prompt)

	def test_a_background_agent_is_untouched(self):
		"""Only a chat turn has a person's message; a record-triggered agent's
		prompt must be exactly what its map rendered."""
		with patch("one_bpmn.agents.turn_state.get_turn", return_value={"user_text": "not mine"}):
			prompt = self._dispatch(_instance())

		self.assertEqual(prompt, "Process the latest message.")

	def test_memory_is_searched_with_the_message_not_the_standing_prompt(self):
		"""Recall used the constant driving prompt as its query, so every turn
		of an agent recalled the same memories however different the request."""
		with patch(
			"one_bpmn.agents.memory.tools.memory_search", return_value=[]
		) as ms, patch("one_bpmn.agents.memory.tools.memory_write"):
			self._dispatch(
				_chat_instance(),
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)

		query = ms.call_args[0][2]
		self.assertEqual(query, "add a status field")

	def test_memory_still_precedes_everything(self):
		with patch(
			"one_bpmn.agents.memory.tools.memory_search", return_value=[{"content": "net-30 rule"}]
		), patch("one_bpmn.agents.memory.tools.memory_write"):
			prompt = self._dispatch(
				_chat_instance(),
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)

		self.assertLess(prompt.index("net-30 rule"), prompt.index("Process the latest message."))
		self.assertLess(prompt.index("Process the latest message."), prompt.index("add a status field"))


# ── WI-002163: bounded, on-topic recall ─────────────────────────────────────
# A constant driving prompt used to recall the same memories on every run
# (fixed above, WI-002169); this covers what that fix alone doesn't: a greeting
# still has no signal worth searching memory with, and nothing bounded the
# injected block's SIZE — aiMemoryLimit only bounds its count.


class TestSmallTalkGate(TestTheUserMessageReachesTheModel):
	"""Reuses TestTheUserMessageReachesTheModel's setUp/_dispatch — same
	mocked observability, same chat-instance fixture."""

	def test_greeting_skips_recall_entirely(self):
		with patch("one_bpmn.agents.memory.tools.memory_search") as ms:
			self._dispatch(
				_chat_instance(),
				{"user_text": "hi"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		ms.assert_not_called()

	def test_acknowledgement_skips_recall(self):
		with patch("one_bpmn.agents.memory.tools.memory_search") as ms:
			self._dispatch(
				_chat_instance(),
				{"user_text": "ok thanks"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		ms.assert_not_called()

	def test_a_real_request_still_recalls(self):
		"""The expensive mistake: refusing recall a real request needed."""
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]) as ms:
			self._dispatch(
				_chat_instance(),
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		ms.assert_called_once()

	def test_a_greeting_with_a_real_request_still_recalls(self):
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]) as ms:
			self._dispatch(
				_chat_instance(),
				{"user_text": "hi, can you create a form for blockers"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		ms.assert_called_once()


class TestRecallSkipsWhenTheTurnMessageIsUnresolved(TestTheUserMessageReachesTheModel):
	"""Observed live (BA site instance trpucrg6cs, run trv5ba6h5a): the first
	message of a brand-new conversation dispatched before the map's turn store
	was seeded, so _turn_user_message found nothing, and recall fell back to
	Logix's constant driving prompt ("HARD PIPELINE RULES...") as its query —
	the same "same memories on every request" defect this story exists to
	close, just narrowed to this one turn.

	The fix must not touch _turn_user_message/turn_state at all (that's
	WI-002169's territory, and the live map itself is out of reach here) — it
	only has to stop the recall query from falling back to a driving-prompt
	template when the real message couldn't be found for a chat turn.
	"""

	def test_no_recall_when_the_turn_message_cannot_be_resolved(self):
		"""task.data carries no user_text and the turn store has nothing either
		— exactly the turn-1 timing gap. aiUserPrompt is a Logix-style constant
		driving prompt, not anything the person said."""
		with patch("one_bpmn.agents.turn_state.get_turn", return_value={}), patch(
			"one_bpmn.agents.memory.tools.memory_search"
		) as ms:
			self._dispatch(
				_chat_instance(),
				{},  # no user_text on the task either
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
				aiUserPrompt="Process the latest user message now. HARD PIPELINE RULES: ...",
			)
		ms.assert_not_called()

	def test_recall_query_is_blank_when_unresolved(self):
		with patch("one_bpmn.agents.turn_state.get_turn", return_value={}), patch(
			"one_bpmn.agents.memory.tools.memory_search"
		):
			self._dispatch(
				_chat_instance(),
				{},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		# recall_query is only observable via create_ai_run's kwargs, which
		# TestTheUserMessageReachesTheModel's setUp doesn't capture — assert
		# through the same _CAPTURED path other tests in this class use isn't
		# possible for a kwarg, so this checks the user-facing consequence
		# instead: no memory block was ever built, so none was injected.
		self.assertNotIn("Relevant memory:", _CAPTURED["config"].user_prompt)

	def test_background_agent_still_recalls_with_its_own_prompt(self):
		"""Regression guard: a non-chat instance is never a chat turn, so the
		new guard must never fire for it — its user_prompt IS real content."""
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]) as ms:
			self._dispatch(
				_instance(),
				{},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
				aiUserPrompt="handle order #4471",
			)
		ms.assert_called_once()
		self.assertEqual(ms.call_args[0][2], "handle order #4471")

	def test_a_map_that_renders_its_own_copy_still_recalls_with_it(self):
		"""Regression guard: when the map embeds the real message into
		aiUserPrompt itself (raw_user_message found, then deduped away because
		it's already in user_prompt), the new guard must not fire — user_prompt
		here is a real, rendered message, not a template."""
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]) as ms:
			self._dispatch(
				_chat_instance(),
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
				aiUserPrompt="Latest user message: {{ user_text }}",
			)
		ms.assert_called_once()
		self.assertEqual(ms.call_args[0][2], "Latest user message: add a status field")


class TestIsSmallTalk(FrappeTestCase):
	"""_is_small_talk directly — the gate other tests exercise through dispatch."""

	def test_greetings_and_acknowledgements(self):
		for message in (
			"hi", "Hi!", "hello", "hey there", "yo", "good morning", "thanks",
			"thank you", "ok", "okay, thanks", "test", "who are you",
		):
			self.assertTrue(D._is_small_talk(message), f"{message!r} should be small talk")

	def test_empty_or_wordless(self):
		for message in ("", "   ", "?", "👋"):
			self.assertTrue(D._is_small_talk(message), f"{message!r} should be small talk")

	def test_real_requests_are_never_small_talk(self):
		for message in (
			"add a status field",
			"a form to log site inspections with a date, an inspector and a pass/fail result",
			"remove the serial number field",
			"delete the invoice table",
			"hi, can you create a form for blockers",
			"ok now add an attachment field",
		):
			self.assertFalse(D._is_small_talk(message), f"{message!r} should not be small talk")


class TestBoundMemoriesToBudget(FrappeTestCase):
	"""_bound_memories_to_budget directly — the truncation dispatch applies to
	whatever memory_search returns, before _format_memory_block renders it."""

	def test_under_budget_is_unchanged(self):
		memories = [{"content": "short fact"}]
		self.assertEqual(D._bound_memories_to_budget(memories, 800), memories)

	def test_zero_or_blank_budget_is_a_noop(self):
		memories = [{"content": "x" * 10_000}]
		self.assertEqual(D._bound_memories_to_budget(memories, 0), memories)
		self.assertEqual(D._bound_memories_to_budget(memories, None), memories)

	def test_lowest_ranked_memories_are_dropped_first(self):
		# Rank order is memory_search's contract (relevance/recency); the
		# budget must respect it, not reorder or skip ahead to something smaller.
		# ~26 tokens each rendered (25 content + the "\n- " join); a header of
		# ~56 tokens leaves room for one at a 90-token budget, not two.
		memories = [{"content": "a" * 100}, {"content": "b" * 100}, {"content": "c" * 100}]
		kept = D._bound_memories_to_budget(memories, 90)
		self.assertEqual(kept, [memories[0]])

	def test_single_oversized_memory_is_truncated_not_dropped(self):
		"""AC4: the block must never exceed budget, including a raw-mode memory
		with no size cap of its own — even the sole, best-ranked memory is cut
		to fit rather than sent whole over budget or left empty."""
		memories = [{"content": "z" * 10_000}]
		kept = D._bound_memories_to_budget(memories, 100)
		self.assertEqual(len(kept), 1)
		self.assertLess(len(kept[0]["content"]), 10_000)
		self.assertGreater(len(kept[0]["content"]), 0)

	def test_result_never_exceeds_the_budget(self):
		from one_bpmn.agents.memory.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

		memories = [{"content": "word " * 200} for _ in range(5)]
		budget = 100
		kept = D._bound_memories_to_budget(memories, budget)
		block = D._format_memory_block(kept)
		self.assertLessEqual(estimate_tokens({"content": block}, DEFAULT_CHARS_PER_TOKEN), budget)


class TestMemoryTokenBudgetInDispatch(TestTheUserMessageReachesTheModel):
	"""End-to-end: dispatch_ai_agent honours aiMemoryTokenBudget (default and
	per-agent override) on whatever memory_search returns."""

	def test_default_budget_bounds_an_oversized_raw_mode_memory(self):
		from one_bpmn.agents.memory.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

		with patch(
			"one_bpmn.agents.memory.tools.memory_search",
			return_value=[{"content": "z" * 50_000}],  # unbounded raw-write content
		), patch("one_bpmn.agents.memory.tools.memory_write"):
			prompt = self._dispatch(
				_chat_instance(),
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)

		# Isolate the memory block: everything before the instructions text
		# (the driving prompt, constant across this fixture's dispatch calls),
		# not "User message:" — that split would also count the instructions
		# themselves, which aiMemoryTokenBudget was never meant to bound.
		memory_block = prompt.split("Process the latest message.")[0].rstrip("\n")
		self.assertLessEqual(
			estimate_tokens({"content": memory_block}, DEFAULT_CHARS_PER_TOKEN),
			D.DEFAULT_MEMORY_TOKEN_BUDGET,
		)

	def test_per_agent_budget_override(self):
		from one_bpmn.agents.memory.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

		with patch(
			"one_bpmn.agents.memory.tools.memory_search",
			return_value=[{"content": "z" * 50_000}],
		), patch("one_bpmn.agents.memory.tools.memory_write"):
			prompt = self._dispatch(
				_chat_instance(),
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
				aiMemoryTokenBudget=100,
			)

		memory_block = prompt.split("Process the latest message.")[0].rstrip("\n")
		self.assertLessEqual(estimate_tokens({"content": memory_block}, DEFAULT_CHARS_PER_TOKEN), 100)


class TestRecallObservability(FrappeTestCase):
	"""AC3/AC5: the recall query and injected size are recorded per run, not
	only visible baked into the rendered prompt."""

	def setUp(self):
		_CAPTURED.clear()
		self.create_ai_run_mock = patch(
			"one_bpmn.agents.observability.create_ai_run",
			return_value=SimpleNamespace(name="RUN-FAKE", stub=False),
		).start()
		self.addCleanup(patch.stopall)
		for target in (
			"one_bpmn.agents.observability.record_ai_step",
			"one_bpmn.agents.observability.finalize_ai_run",
			"one_bpmn.agents.observability.finalize_ai_run_on_exception",
			"frappe.db.commit",
		):
			patch(target).start()
		patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task").start()

	def _dispatch(self, task_data=None, **cfg):
		task = SimpleNamespace(
			data=dict(task_data or {}), task_spec=SimpleNamespace(bpmn_id="Act_1", name="Act_1")
		)
		config = {"aiBackend": "faketest", "aiSystemPrompt": "SYS", "aiUserPrompt": "Process the latest message."}
		config.update(cfg)
		D.dispatch_ai_agent(_chat_instance(), task, config, "Act_1")

	def test_recall_query_is_the_user_message_not_the_template(self):
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]):
			self._dispatch(
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		kwargs = self.create_ai_run_mock.call_args.kwargs
		self.assertEqual(kwargs["recall_query"], "add a status field")

	def test_recall_query_is_blank_when_small_talk(self):
		with patch("one_bpmn.agents.memory.tools.memory_search") as ms:
			self._dispatch(
				{"user_text": "hi"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		ms.assert_not_called()
		kwargs = self.create_ai_run_mock.call_args.kwargs
		self.assertEqual(kwargs["recall_query"], "")

	def test_memory_injected_tokens_reflects_the_bounded_block(self):
		with patch(
			"one_bpmn.agents.memory.tools.memory_search", return_value=[{"content": "net-30 rule"}]
		):
			self._dispatch(
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		kwargs = self.create_ai_run_mock.call_args.kwargs
		self.assertGreater(kwargs["memory_injected_tokens"], 0)
		self.assertLessEqual(kwargs["memory_injected_tokens"], D.DEFAULT_MEMORY_TOKEN_BUDGET)

	def test_memory_injected_tokens_is_zero_when_nothing_found(self):
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]):
			self._dispatch(
				{"user_text": "add a status field"},
				aiLongTermMemory="enabled",
				aiMemoryScope="Agent",
			)
		kwargs = self.create_ai_run_mock.call_args.kwargs
		self.assertEqual(kwargs["memory_injected_tokens"], 0)


class TestMemoryTargetUserScope(FrappeTestCase):
	"""_resolve_memory_target: User scopes carry the requesting user, the blank
	default follows the agent type, and Agent-only never carries a user."""

	def _target(self, scope, agent_type="Chat", user="alice@example.com"):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D

		instance = SimpleNamespace(process_model="PM-1", context_doctype="Employee", context_docname="EMP-1")
		cfg = {"aiMemoryScope": scope, "aiAgentConfig": "CFG-1"}
		with patch("frappe.db.get_value", return_value=agent_type), patch.object(D, "_requesting_user", return_value=user):
			return D._resolve_memory_target(cfg, instance, "Act_1")

	def test_blank_scope_defaults_by_agent_type(self):
		self.assertEqual(self._target("", "Chat"), ("Agent", {"agent_element": "Act_1", "user": "alice@example.com"}))
		self.assertEqual(self._target("", "Background"), ("Agent", "Act_1"))

	def test_agent_only_carries_no_user(self):
		self.assertEqual(self._target("Agent"), ("Agent", "Act_1"))

	def test_user_variants(self):
		self.assertEqual(self._target("User and Process"), ("Process", {"process": "PM-1", "user": "alice@example.com"}))
		self.assertEqual(
			self._target("User and Entity"),
			("Entity", {"reference_doctype": "Employee", "reference_name": "EMP-1", "user": "alice@example.com"}),
		)

	def test_guest_falls_back_to_shared(self):
		self.assertEqual(self._target("User and Agent", user=None), ("Agent", "Act_1"))
