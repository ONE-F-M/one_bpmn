# Copyright (c) 2026, one-fm and contributors
# WI-001751: what run_agent_loop returns when it runs out of turns.
#
# The loop used to return text="" on the turn cap. For an agent declaring
# response_format="json" that arrives at validation as "invalid JSON: Expecting
# value: line 1 column 1 (char 0)" — a message that blames the model for a
# malformed reply when in fact the loop simply ran out of turns, and which is
# indistinguishable from the model genuinely answering in prose. Carrying the
# last narration out instead makes the two cases tellable apart, and keeps the
# partial progress visible to whoever reads the run.

from __future__ import annotations

import asyncio

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec


def _tool(name="noop"):
	return ToolSpec(fn=lambda **kw: "done", name=name, description="d", parameters={}, required=[])


class _AlwaysCallsTools:
	"""Never produces a final answer, so the loop always hits the cap."""

	def __init__(self, narration):
		self.narration = narration
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.calls += 1
		return StepResult(
			content=self.narration,
			tool_calls=[StepToolCall(id=f"c{self.calls}", name="noop", arguments={})],
		)


class TestStepLoopTurnCap(FrappeTestCase):
	def test_turn_cap_carries_the_last_narration_out(self):
		adapter = _AlwaysCallsTools("Now I'll add the test cases:")
		completion, suspension = asyncio.run(
			run_agent_loop(adapter, system="s", user="u", tools=[_tool()], max_turns=3)
		)
		self.assertIsNone(suspension)
		self.assertTrue(completion.hit_turn_cap)
		self.assertEqual(completion.text, "Now I'll add the test cases:")

	def test_turn_cap_respects_the_limit(self):
		adapter = _AlwaysCallsTools("working")
		completion, _ = asyncio.run(
			run_agent_loop(adapter, system="s", user="u", tools=[_tool()], max_turns=3)
		)
		self.assertEqual(adapter.calls, 3)
		self.assertEqual(len(completion.trace), 3)

	def test_turn_cap_with_no_narration_is_still_empty(self):
		"""Nothing is invented: a silent model still yields empty text, and
		hit_turn_cap is what tells the caller why."""
		adapter = _AlwaysCallsTools("")
		completion, _ = asyncio.run(
			run_agent_loop(adapter, system="s", user="u", tools=[_tool()], max_turns=2)
		)
		self.assertTrue(completion.hit_turn_cap)
		self.assertEqual(completion.text, "")

	def test_a_real_final_answer_is_not_treated_as_a_cap(self):
		class Answers:
			async def step(self, system, transcript, tools=None, max_tokens=16384):
				return StepResult(content="all done", tool_calls=[])

		completion, _ = asyncio.run(
			run_agent_loop(Answers(), system="s", user="u", tools=[_tool()], max_turns=3)
		)
		self.assertFalse(completion.hit_turn_cap)
		self.assertEqual(completion.text, "all done")
