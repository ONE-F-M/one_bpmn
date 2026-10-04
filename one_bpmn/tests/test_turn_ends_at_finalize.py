# Copyright (c) 2026, one-fm and contributors
"""A turn whose reply is already captured must not pay for another model call.

The old loop always went back to the model after the last tool result, and on a
finalize-style turn there was nothing left to say: measured on Logix run
om8mj9cenv, that closing call returned 0 characters for $0.00287 out of a
$0.01425 turn. These tests pin the call count, because the saving IS the call.
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


def _tool_call(name):
	return StepToolCall(id=f"c-{name}", name=name, arguments={})


def _answering_tool():
	def fn(**kwargs):
		# What every finalize-style stage tool does through update_turn().
		frappe.flags[TURN_ANSWERED_FLAG] = True
		return '{"finalized": true}'

	return ToolSpec(fn=fn, name="finalize", description="answer the turn")


def _plain_tool():
	return ToolSpec(fn=lambda **kw: "looked-up", name="lookup", description="a read")


def _run(adapter, tools):
	return asyncio.run(
		run_agent_loop(adapter, system="sys", user="do it", tools=tools, max_tokens=100, max_turns=10)
	)


class TestTurnEndsAtFinalize(FrappeTestCase):
	def setUp(self):
		frappe.flags[TURN_ANSWERED_FLAG] = False

	def test_the_closing_model_call_is_gone(self):
		adapter = CountingAdapter([
			StepResult(content="calling finalize", tool_calls=[_tool_call("finalize")],
			           prompt_tokens=2863, completion_tokens=50),
		])
		completion, suspension = _run(adapter, [_answering_tool()])
		self.assertIsNone(suspension)
		self.assertEqual(adapter.calls, 1, "the answered turn cost one model call, not two")
		self.assertEqual(len(completion.trace), 1)
		self.assertEqual(completion.text, "calling finalize")

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
