# Copyright (c) 2026, one-fm and contributors
"""A turn whose reply is already captured must not pay for another model call.

The old loop always went back to the model after the last tool result, and on a
finalize-style turn there was nothing left to say: measured on Logix run
om8mj9cenv, that closing call returned 0 characters for $0.00287 out of a
$0.01425 turn. These tests pin the call count, because the saving IS the call.

WI-002187 adds a second, independent way a turn can end early: any tool named
in ``terminal_tools`` (default ``{"finalize"}``) ends the turn the instant it
runs, and the REPLY comes from that call's own ``response`` argument — not
from whatever the model narrated alongside it. That distinction is the whole
point: LuCrusher run foac1717np had a 1,504-char answer sitting in the
finalize call's arguments while the turn's narration (and so the old
final_output) was empty.
"""

import asyncio

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec
from one_bpmn.agents.turn_state import TURN_ANSWERED_FLAG


class CountingAdapter:
	"""Scripted step() responses that counts how many model calls were made."""

	def __init__(self, steps):
		self.steps = list(steps)
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.calls += 1
		if not self.steps:
			raise AssertionError("the loop asked the model again after the turn was answered")
		return self.steps.pop(0)


def _tool_call(name, arguments=None):
	return StepToolCall(id=f"c-{name}", name=name, arguments=arguments or {})


def _answering_tool(name="clarify"):
	"""A stage tool that ends the turn through turn_state, not through the
	name-based terminal_tools list — e.g. "clarify", which finalize's
	default entry does not cover."""
	def fn(**kwargs):
		# What every finalize-style stage tool does through update_turn().
		frappe.flags[TURN_ANSWERED_FLAG] = True
		return '{"finalized": true}'

	return ToolSpec(fn=fn, name=name, description="answer the turn")


def _finalize_tool():
	"""An ordinary "finalize" ToolSpec — no turn_state wiring at all. Its
	return value is what a caller that ignores the "response" argument
	would fall back to."""
	return ToolSpec(fn=lambda **kwargs: "ok", name="finalize", description="answer the turn")


def _plain_tool():
	return ToolSpec(fn=lambda **kw: "looked-up", name="lookup", description="a read")


def _run(adapter, tools, **kwargs):
	return asyncio.run(
		run_agent_loop(adapter, system="sys", user="do it", tools=tools, max_tokens=100, max_turns=10, **kwargs)
	)


class TestTurnEndsAtFinalize(FrappeTestCase):
	def setUp(self):
		frappe.flags[TURN_ANSWERED_FLAG] = False

	def test_finalize_reply_comes_from_arguments_not_narration(self):
		"""The bug: the model calls finalize with the real answer in its
		arguments but writes nothing (or something unrelated) as narration."""
		adapter = CountingAdapter([
			StepResult(
				content="",
				tool_calls=[_tool_call("finalize", {"response": "the 1504-char answer"})],
				prompt_tokens=2863, completion_tokens=50,
			),
		])
		completion, suspension = _run(adapter, [_finalize_tool()])
		self.assertIsNone(suspension)
		self.assertEqual(adapter.calls, 1, "the answered turn cost one model call, not two")
		self.assertEqual(completion.text, "the 1504-char answer")
		self.assertFalse(completion.no_terminal_tool)

	def test_a_configured_terminal_tool_beyond_the_default(self):
		"""aiTerminalTools lets a shape name its own closing tool."""
		adapter = CountingAdapter([
			StepResult(
				content="",
				tool_calls=[_tool_call("submit_answer", {"response": "done"})],
				prompt_tokens=10, completion_tokens=5,
			),
		])
		tool = ToolSpec(fn=lambda **kw: "ok", name="submit_answer", description="answer")
		completion, _ = _run(adapter, [tool], terminal_tools=["finalize", "submit_answer"])
		self.assertEqual(adapter.calls, 1)
		self.assertEqual(completion.text, "done")
		self.assertFalse(completion.no_terminal_tool)

	def test_plain_text_with_no_tool_call_is_flagged(self):
		"""A model that never calls a terminal tool still gets its text kept —
		just marked so evals can tell it apart from an authoritative reply."""
		adapter = CountingAdapter([
			StepResult(content="here is the answer", tool_calls=[], prompt_tokens=20, completion_tokens=9),
		])
		completion, _ = _run(adapter, [_finalize_tool()])
		self.assertEqual(completion.text, "here is the answer")
		self.assertTrue(completion.no_terminal_tool)

	def test_stage_tool_flag_path_still_works_for_non_default_names(self):
		"""turn_state's TURN_ANSWERED_FLAG remains the fallback for a tool
		(like "clarify") that isn't in terminal_tools."""
		adapter = CountingAdapter([
			StepResult(content="calling clarify", tool_calls=[_tool_call("clarify")],
			           prompt_tokens=2863, completion_tokens=50),
		])
		completion, suspension = _run(adapter, [_answering_tool("clarify")])
		self.assertIsNone(suspension)
		self.assertEqual(adapter.calls, 1, "the answered turn cost one model call, not two")
		self.assertEqual(len(completion.trace), 1)
		self.assertEqual(completion.text, "calling clarify")
		self.assertFalse(completion.no_terminal_tool)

	def test_a_plain_tool_still_goes_back_to_the_model(self):
		"""Only an answered turn stops early — an ordinary read must continue."""
		adapter = CountingAdapter([
			StepResult(content="", tool_calls=[_tool_call("lookup")], prompt_tokens=10, completion_tokens=5),
			StepResult(content="here is the answer", tool_calls=[], prompt_tokens=20, completion_tokens=9),
		])
		completion, suspension = _run(adapter, [_plain_tool()])
		self.assertIsNone(suspension)
		self.assertEqual(adapter.calls, 2)
		self.assertEqual(completion.text, "here is the answer")

	def test_the_flag_does_not_leak_into_the_next_run(self):
		"""A stale flag must not end an unrelated turn before it starts."""
		frappe.flags[TURN_ANSWERED_FLAG] = True
		adapter = CountingAdapter([
			StepResult(content="", tool_calls=[_tool_call("lookup")], prompt_tokens=10, completion_tokens=5),
			StepResult(content="done", tool_calls=[], prompt_tokens=20, completion_tokens=9),
		])
		completion, _ = _run(adapter, [_plain_tool()])
		self.assertEqual(adapter.calls, 2)
		self.assertEqual(completion.text, "done")
		self.assertFalse(frappe.flags.get(TURN_ANSWERED_FLAG))
