# Copyright (c) 2026, one-fm and contributors
"""The tool loop tells an agent how many turns it has left, and to wrap up as the cap nears."""

from __future__ import annotations

import asyncio

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec


def _tool(name):
	return ToolSpec(fn=lambda **kw: "done", name=name, description="d", parameters={}, required=[])


class _Calls:
	"""Calls the named tools one per turn and keeps what each tool result looked like."""

	def __init__(self, *names):
		self.names = list(names)
		self.seen = []

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		results = [entry for entry in transcript if entry.get("role") == "tool_results"]
		self.seen.append(results[-1]["results"][-1]["content"] if results else None)
		name = self.names[min(len(self.seen) - 1, len(self.names) - 1)]
		return StepResult(content="", tool_calls=[StepToolCall(id=f"c{len(self.seen)}", name=name, arguments={})])


def _run(adapter, max_turns, budget_notes=True):
	tools = [_tool("grep_files"), _tool("edit_file")]
	return asyncio.run(
		run_agent_loop(adapter, system="s", user="u", tools=tools, max_turns=max_turns, budget_notes=budget_notes)
	)


class TestStepLoopBudget(FrappeTestCase):
	def test_each_tool_result_carries_the_turn_count(self):
		adapter = _Calls("grep_files")
		_run(adapter, max_turns=8)
		self.assertIn("[Run budget: turn 1 of 8, 7 left, 0 edit(s) made.]", adapter.seen[1])

	def test_an_early_note_is_a_count_and_not_an_instruction(self):
		adapter = _Calls("grep_files")
		_run(adapter, max_turns=8)
		self.assertNotIn("Stop exploring", adapter.seen[1])

	def test_past_three_quarters_of_the_cap_the_note_says_to_wrap_up(self):
		adapter = _Calls("grep_files")
		_run(adapter, max_turns=8)
		self.assertIn("Stop exploring", adapter.seen[6])
		self.assertIn("turn 6 of 8", adapter.seen[6])

	def test_the_last_turn_is_named(self):
		adapter = _Calls("grep_files")
		_run(adapter, max_turns=8)
		self.assertIn("This is your last turn", adapter.seen[7])

	def test_edits_made_are_counted(self):
		adapter = _Calls("grep_files", "edit_file", "grep_files")
		_run(adapter, max_turns=5)
		self.assertIn("1 edit(s) made", adapter.seen[3])

	def test_the_note_sits_outside_the_tool_data(self):
		adapter = _Calls("grep_files")
		_run(adapter, max_turns=4)
		self.assertTrue(adapter.seen[1].rstrip().endswith("edit(s) made.]"))
		self.assertGreater(adapter.seen[1].index("[Run budget"), adapter.seen[1].index("done"))

	def test_without_the_flag_the_results_are_untouched(self):
		adapter = _Calls("grep_files")
		_run(adapter, max_turns=4, budget_notes=False)
		self.assertNotIn("Run budget", adapter.seen[1])
