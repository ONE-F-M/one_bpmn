# Copyright (c) 2026, one-fm and contributors
# Durable AI Agent HITL, story 1 — step-driven (resumable) executor loop.
#
# Covers:
# - automatic-only runs behave like the old adapter-internal loop (final
#   answer, trace shape, token accounting, turn cap)
# - a human-tool selection yields a suspension outcome instead of executing
# - resume re-enters the conversation with the human result and finishes
# - DirectApiExecutor maps a suspension to ErrorCode.SUSPENDED
import asyncio
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext
from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec


class FakeStepAdapter:
	"""Scripted step() responses; records every transcript it was given."""

	def __init__(self, steps):
		self.steps = list(steps)
		self.seen_transcripts = []
		self.seen_systems = []

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.seen_systems.append(system)
		# Deep-ish copy so later mutation doesn't rewrite history
		self.seen_transcripts.append([dict(e) for e in transcript])
		return self.steps.pop(0)


def _auto_tool(name="lookup", fn=None):
	return ToolSpec(
		fn=fn or (lambda **kw: f"{name}-result"),
		name=name,
		description=f"{name} tool",
	)


def _human_tool(name="approval"):
	return ToolSpec(
		fn=lambda **kw: (_ for _ in ()).throw(AssertionError("human fn called")),
		name=name,
		description="ask a person",
		human=True,
	)


def _run(adapter, tools, max_turns=10, resume=None, user="do the thing"):
	return asyncio.run(
		run_agent_loop(
			adapter,
			system="sys",
			user=user,
			tools=tools,
			max_tokens=100,
			max_turns=max_turns,
			resume=resume,
		)
	)


class TestStepLoopAutomatic(FrappeTestCase):
	def test_final_answer_no_tools_called(self):
		adapter = FakeStepAdapter([StepResult(content="done", prompt_tokens=10, completion_tokens=2)])
		completion, suspension = _run(adapter, [_auto_tool()])

		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "done")
		self.assertFalse(completion.hit_turn_cap)
		self.assertEqual(len(completion.trace), 1)
		self.assertEqual(completion.trace[0].role, "assistant")
		self.assertEqual(completion.prompt_tokens, 10)
		self.assertEqual(completion.completion_tokens, 2)
		# transcript given to the model: just the user prompt
		self.assertEqual(
			adapter.seen_transcripts[0], [{"role": "user", "content": "do the thing"}]
		)

	def test_tool_call_executes_and_feeds_back(self):
		calls = {}

		def fn(**kw):
			calls.update(kw)
			return "42"

		adapter = FakeStepAdapter([
			StepResult(
				content="checking",
				tool_calls=[StepToolCall(id="c1", name="lookup", arguments={"q": "x"})],
				prompt_tokens=100,
				completion_tokens=10,
			),
			StepResult(content="answer: 42", prompt_tokens=120, completion_tokens=5),
		])
		completion, suspension = _run(adapter, [_auto_tool(fn=fn)])

		self.assertIsNone(suspension)
		self.assertEqual(calls, {"q": "x"})
		self.assertEqual(completion.text, "answer: 42")
		# trace: one tool turn + one assistant turn, tokens summed across both
		self.assertEqual([t.role for t in completion.trace], ["tool", "assistant"])
		self.assertEqual(completion.trace[0].tool_calls[0].name, "lookup")
		self.assertEqual(completion.trace[0].tool_calls[0].result, "42")
		self.assertEqual(completion.prompt_tokens, 220)
		self.assertEqual(completion.completion_tokens, 15)
		# second model call saw assistant entry + tool_results entry
		second = adapter.seen_transcripts[1]
		self.assertEqual(
			[e["role"] for e in second], ["user", "assistant", "tool_results"]
		)
		self.assertEqual(
			second[2]["results"], [{"id": "c1", "name": "lookup", "content": "42"}]
		)

	def test_unknown_tool_and_tool_error_strings(self):
		def boom(**kw):
			raise ValueError("nope")

		adapter = FakeStepAdapter([
			StepResult(
				tool_calls=[
					StepToolCall(id="c1", name="ghost", arguments={}),
					StepToolCall(id="c2", name="lookup", arguments={}),
				],
			),
			StepResult(content="ok"),
		])
		completion, _ = _run(adapter, [_auto_tool(fn=boom)])
		results = adapter.seen_transcripts[1][2]["results"]
		self.assertEqual(results[0]["content"], "Unknown tool: ghost")
		self.assertEqual(results[1]["content"], "Error calling lookup: nope")
		self.assertEqual(completion.text, "ok")

	def test_turn_cap_sets_flag_with_partial_trace(self):
		looping = StepResult(
			tool_calls=[StepToolCall(id="c", name="lookup", arguments={})],
			prompt_tokens=10,
			completion_tokens=1,
		)
		adapter = FakeStepAdapter([looping, looping, looping])
		completion, suspension = _run(adapter, [_auto_tool()], max_turns=3)

		self.assertIsNone(suspension)
		self.assertTrue(completion.hit_turn_cap)
		self.assertEqual(completion.text, "")
		self.assertEqual(len(completion.trace), 3)


class TestStepLoopSuspension(FrappeTestCase):
	def test_human_tool_suspends_with_deferred_results(self):
		adapter = FakeStepAdapter([
			StepResult(
				content="need approval",
				tool_calls=[
					StepToolCall(id="a1", name="lookup", arguments={"q": "x"}),
					StepToolCall(id="h1", name="approval", arguments={"request": "ok?"}),
					StepToolCall(id="h2", name="approval", arguments={"request": "again?"}),
				],
				prompt_tokens=50,
				completion_tokens=5,
			),
		])
		completion, suspension = _run(adapter, [_auto_tool(), _human_tool()])

		self.assertIsNone(completion)
		self.assertEqual(suspension.pending_call["id"], "h1")
		self.assertEqual(suspension.pending_call["name"], "approval")
		self.assertEqual(suspension.pending_call["arguments"], {"request": "ok?"})
		self.assertEqual(suspension.turns_used, 1)
		# automatic sibling executed; the SECOND human call was refused inline
		contents = {r["id"]: r["content"] for r in suspension.deferred_results}
		self.assertEqual(contents["a1"], "lookup-result")
		self.assertIn("only one human task", contents["h2"])
		# transcript ends on the assistant entry that requested the calls
		self.assertEqual(suspension.transcript[-1]["role"], "assistant")
		self.assertEqual(len(suspension.transcript[-1]["tool_calls"]), 3)
		# segment trace + tokens are checkpoint-ready (plain dicts/ints)
		self.assertEqual(suspension.trace[0]["role"], "tool")
		self.assertEqual(suspension.prompt_tokens, 50)
		self.assertEqual(suspension.completion_tokens, 5)

	def test_resume_completes_turn_and_finishes(self):
		adapter = FakeStepAdapter([
			StepResult(content="approved, done", prompt_tokens=80, completion_tokens=4),
		])
		resume = {
			"transcript": [
				{"role": "user", "content": "do the thing"},
				{
					"role": "assistant",
					"content": "need approval",
					"tool_calls": [
						{"id": "a1", "name": "lookup", "arguments": {}},
						{"id": "h1", "name": "approval", "arguments": {"request": "ok?"}},
					],
				},
			],
			"pending_call": {"id": "h1", "name": "approval", "arguments": {"request": "ok?"}},
			"deferred_results": [{"id": "a1", "name": "lookup", "content": "42"}],
			"turns_used": 1,
			"human_result": '{"action": "Approve"}',
		}
		completion, suspension = _run(adapter, [_auto_tool(), _human_tool()], resume=resume)

		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "approved, done")
		# the model saw the completed turn: deferred result + human result
		seen = adapter.seen_transcripts[0]
		self.assertEqual(seen[-1]["role"], "tool_results")
		self.assertEqual(
			seen[-1]["results"],
			[
				{"id": "a1", "name": "lookup", "content": "42"},
				{"id": "h1", "name": "approval", "content": '{"action": "Approve"}'},
			],
		)

	def test_turn_cap_is_cumulative_across_suspension(self):
		adapter = FakeStepAdapter([])  # must never be called
		resume = {
			"transcript": [{"role": "user", "content": "x"}],
			"pending_call": {"id": "h1", "name": "approval", "arguments": {}},
			"deferred_results": [],
			"turns_used": 3,
			"human_result": "yes",
		}
		completion, suspension = _run(
			adapter, [_human_tool()], max_turns=3, resume=resume
		)
		self.assertIsNone(suspension)
		self.assertTrue(completion.hit_turn_cap)
		self.assertEqual(adapter.seen_transcripts, [])

	def test_second_suspension_after_resume(self):
		adapter = FakeStepAdapter([
			StepResult(
				tool_calls=[StepToolCall(id="h9", name="approval", arguments={"request": "more?"})],
			),
		])
		resume = {
			"transcript": [
				{"role": "user", "content": "x"},
				{
					"role": "assistant",
					"content": "",
					"tool_calls": [{"id": "h1", "name": "approval", "arguments": {}}],
				},
			],
			"pending_call": {"id": "h1", "name": "approval", "arguments": {}},
			"deferred_results": [],
			"turns_used": 1,
			"human_result": "yes",
		}
		completion, suspension = _run(adapter, [_human_tool()], resume=resume)

		self.assertIsNone(completion)
		self.assertEqual(suspension.pending_call["id"], "h9")
		self.assertEqual(suspension.turns_used, 2)
		# the new transcript carries the completed first human turn
		roles = [e["role"] for e in suspension.transcript]
		self.assertEqual(roles, ["user", "assistant", "tool_results", "assistant"])


class TestExecutorSuspensionMapping(FrappeTestCase):
	"""DirectApiExecutor._run_with_tools maps loop outcomes to ExecutorResult."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("AI Provider Credentials", "_Test HITL Provider"):
			frappe.get_doc({
				"doctype": "AI Provider Credentials",
				"provider_name": "_Test HITL Provider",
				"provider_type": "OpenAI",
				"api_key": "test-key-not-real",
				"default_model": "gpt-test",
				"enabled": 1,
			}).insert(ignore_permissions=True)

	def _execute(self, adapter, tools, resume_state=None):
		from one_bpmn.agents.executor.direct_api import DirectApiExecutor

		config = ExecutorConfig(
			provider_name="_Test HITL Provider",
			tools=tools,
			max_tool_calls=5,
			resume_state=resume_state,
		)
		with patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter",
			return_value=adapter,
		):
			return DirectApiExecutor().run(config, ExecutorContext())

	def test_suspension_maps_to_suspended_result(self):
		adapter = FakeStepAdapter([
			StepResult(
				tool_calls=[StepToolCall(id="h1", name="approval", arguments={"request": "?"})],
				prompt_tokens=30,
				completion_tokens=3,
			),
		])
		result = self._execute(adapter, [_human_tool()])

		self.assertEqual(result.error_code, ErrorCode.SUSPENDED)
		self.assertIsNotNone(result.suspension)
		self.assertEqual(result.suspension["pending_call"]["name"], "approval")
		self.assertEqual(result.suspension["turns_used"], 1)
		self.assertEqual(result.token_usage.prompt_tokens, 30)
		self.assertEqual(len(result.trace), 1)

	def test_automatic_run_is_success_with_trace(self):
		adapter = FakeStepAdapter([
			StepResult(
				tool_calls=[StepToolCall(id="c1", name="lookup", arguments={})],
				prompt_tokens=10,
				completion_tokens=1,
			),
			StepResult(content="fin", prompt_tokens=20, completion_tokens=2),
		])
		result = self._execute(adapter, [_auto_tool()])

		self.assertEqual(result.error_code, ErrorCode.SUCCESS)
		self.assertIsNone(result.suspension)
		self.assertEqual(result.output, "fin")
		self.assertEqual(result.token_usage.total_tokens, 33)
		self.assertEqual(len(result.trace), 2)

	def test_turn_cap_maps_to_failed_model_call(self):
		looping = StepResult(tool_calls=[StepToolCall(id="c", name="lookup", arguments={})])
		adapter = FakeStepAdapter([looping] * 5)
		result = self._execute(adapter, [_auto_tool()])

		self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
		self.assertIn("turn cap", result.error_message)
