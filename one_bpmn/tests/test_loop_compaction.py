# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A long tool loop replaces its older turns with a summary and the files read and edited."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorResult, TokenUsage
from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec
from one_bpmn.agents.memory import loop_compaction
from one_bpmn.agents.observability import _CURRENT_RUN_FLAG
from one_bpmn.one_bpmn.patches.v1_0 import coding_agents_compact_their_tool_loop

SUMMARY_CALL = "one_bpmn.agents.memory.loop_compaction.summary_call"


def _summary(text="Read the panel and fixed the import."):
	return ExecutorResult(output=text, token_usage=TokenUsage(prompt_tokens=900, completion_tokens=60))


def _turn(n: int, name: str = "read_file") -> list:
	return [
		{
			"role": "assistant",
			"content": f"step {n}",
			"tool_calls": [{"id": f"c{n}", "name": name, "arguments": {"path": f"src/f{n}.vue"}}],
		},
		{"role": "tool_results", "results": [{"id": f"c{n}", "name": name, "content": "x" * 5000}]},
	]


def _transcript(turns: int, edit_at: int = 2) -> list:
	entries = [{"role": "user", "content": "Fix the broken panel."}]
	for n in range(1, turns + 1):
		entries += _turn(n, "edit_file" if n == edit_at else "read_file")
	return entries


def _compact(transcript, keep_turns=3):
	return loop_compaction.compact_transcript(
		transcript,
		keep_turns=keep_turns,
		model="claude-haiku-4-5",
		agent_model="claude-sonnet-5",
		provider="Claude",
	)


class TestCompactTranscript(FrappeTestCase):
	def test_older_turns_become_one_summary_with_the_files_and_the_task_stays_first(self):
		transcript = _transcript(6)
		with patch(SUMMARY_CALL, return_value=_summary()) as call:
			out = _compact(transcript)
		self.assertTrue(out[0]["content"].startswith("Fix the broken panel.\n\nProgress so far"))
		self.assertIn("Read the panel and fixed the import.", out[0]["content"])
		self.assertIn("Files edited: src/f2.vue", out[0]["content"])
		self.assertEqual(out[0]["compaction"]["read"], ["src/f1.vue", "src/f3.vue"])
		self.assertEqual(out[1:], transcript[-6:])
		self.assertIn("Task: Fix the broken panel.", call.call_args.args[0])
		self.assertLess(len(call.call_args.args[0]), 3 * 5000)

	def test_a_second_compaction_folds_in_the_first(self):
		with patch(SUMMARY_CALL, return_value=_summary("First.")):
			once = _compact(_transcript(6))
		grown = once + _turn(7) + _turn(8) + _turn(9)
		with patch(SUMMARY_CALL, return_value=_summary("Both.")) as call:
			twice = _compact(grown)
		self.assertEqual(call.call_args.args[1], "First.")
		self.assertIn("Task: Fix the broken panel.\n\nTurns:", call.call_args.args[0])
		self.assertEqual([e for e in twice if e.get("compaction")], [twice[0]])
		self.assertEqual(twice[0]["compaction"]["task"], "Fix the broken panel.")
		self.assertEqual(twice[0]["content"].count("Progress so far"), 1)
		self.assertEqual(
			twice[0]["compaction"]["read"],
			["src/f1.vue", "src/f3.vue", "src/f4.vue", "src/f5.vue", "src/f6.vue"],
		)

	def test_too_few_turns_or_a_failed_summary_leaves_the_transcript_alone(self):
		with patch(SUMMARY_CALL, return_value=_summary()) as call:
			self.assertIsNone(_compact(_transcript(3)))
		call.assert_not_called()
		with patch(SUMMARY_CALL, return_value=None):
			self.assertIsNone(_compact(_transcript(6)))

	def test_the_summary_call_is_recorded_as_a_step_of_the_run(self):
		run = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": "agent",
				"status": "Running",
				"started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True, ignore_links=True)
		frappe.flags[_CURRENT_RUN_FLAG] = run.name
		try:
			with patch(SUMMARY_CALL, return_value=_summary()):
				_compact(_transcript(6))
		finally:
			frappe.flags[_CURRENT_RUN_FLAG] = None
		step = frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=["content", "prompt_tokens", "completion_tokens"],
		)[0]
		self.assertTrue(step.content.startswith("[sub-call: compaction via claude-haiku-4-5"))
		self.assertEqual((step.prompt_tokens, step.completion_tokens), (900, 60))


class _GrowingAdapter:
	"""Calls read_file for `turns` calls, each reporting a bigger prompt, then answers."""

	def __init__(self, turns: int):
		self.turns, self.transcripts = turns, []

	async def step(self, system, transcript, tools=None, max_tokens=16384, **_):
		self.transcripts.append([dict(e) for e in transcript])
		n = len(self.transcripts)
		if n > self.turns:
			return StepResult(content="Done.", prompt_tokens=n * 10000)
		call = StepToolCall(id=f"c{n}", name="read_file", arguments={"path": f"src/f{n}.vue"})
		return StepResult(tool_calls=[call], prompt_tokens=n * 10000)


class TestTheLoopCompacts(FrappeTestCase):
	def test_the_call_after_the_threshold_gets_the_compacted_transcript_and_the_trace_is_untouched(self):
		adapter = _GrowingAdapter(turns=8)
		tool = ToolSpec(
			fn=lambda path: "x" * 5000,
			name="read_file",
			description="Read a file.",
			parameters={"path": {"type": "string"}},
			required=["path"],
		)
		with patch(SUMMARY_CALL, return_value=_summary()) as call:
			completion, _ = asyncio.run(
				run_agent_loop(
					adapter,
					system="s",
					user="Fix the broken panel.",
					tools=[tool],
					max_turns=20,
					loop_compaction={
						"threshold": 45000,
						"keep_turns": 2,
						"model": None,
						"agent_model": "claude-sonnet-5",
						"provider": "Claude",
					},
				)
			)
		self.assertEqual(completion.text, "Done.")
		self.assertEqual(len(completion.trace), 9)
		self.assertFalse(any(e.get("compaction") for e in adapter.transcripts[4]))
		self.assertEqual(adapter.transcripts[5][0]["compaction"]["task"], "Fix the broken panel.")
		self.assertEqual(adapter.transcripts[5][1]["role"], "assistant")
		self.assertEqual(call.call_count, 2)

	def test_a_threshold_crossed_before_there_is_anything_old_still_compacts_later(self):
		"""The Dev Agent run s9i3fbi9ig passed the threshold at 5 tool turns with keep_turns 8 and never compacted."""
		adapter = _GrowingAdapter(turns=10)
		tool = ToolSpec(
			fn=lambda path: "x",
			name="read_file",
			description="Read a file.",
			parameters={"path": {"type": "string"}},
		)
		with patch(SUMMARY_CALL, return_value=_summary()):
			asyncio.run(
				run_agent_loop(
					adapter,
					system="s",
					user="Fix the broken panel.",
					tools=[tool],
					max_turns=20,
					loop_compaction={
						"threshold": 25000,
						"keep_turns": 4,
						"model": None,
						"agent_model": "claude-sonnet-5",
						"provider": "Claude",
					},
				)
			)
		self.assertFalse(any(e.get("compaction") for e in adapter.transcripts[4]))
		self.assertTrue(adapter.transcripts[5][0].get("compaction"))

	def test_a_resumed_run_compacts_on_its_first_call(self):
		"""A coding run parks at run_tests and open_pull_request; each resume used to start from a prompt size of 0."""
		calls = []

		class _Answers:
			async def step(self, system, transcript, tools=None, max_tokens=16384, **_):
				calls.append([dict(e) for e in transcript])
				return StepResult(content="Done.", prompt_tokens=20000)

		transcript = [*_transcript(8), _turn(9)[0]]
		resume = {
			"transcript": transcript,
			"turns_used": 9,
			"trace": [
				{"role": "assistant", "content": f"step {n}", "prompt_tokens": n * 10000}
				for n in range(1, 10)
			],
			"pending_call": {"id": "c9", "name": "run_tests", "arguments": {}},
			"human_result": "tests ran",
		}
		with patch(SUMMARY_CALL, return_value=_summary()):
			completion, _ = asyncio.run(
				run_agent_loop(
					_Answers(),
					system="s",
					user="Fix the broken panel.",
					tools=[],
					max_turns=20,
					resume=resume,
					loop_compaction={
						"threshold": 50000,
						"keep_turns": 3,
						"model": None,
						"agent_model": "claude-sonnet-5",
						"provider": "Claude",
					},
				)
			)
		self.assertEqual(completion.text, "Done.")
		self.assertTrue(calls[0][0].get("compaction"))

	def test_no_setting_means_no_compaction(self):
		adapter = _GrowingAdapter(turns=6)
		tool = ToolSpec(
			fn=lambda path: "x",
			name="read_file",
			description="Read a file.",
			parameters={"path": {"type": "string"}},
		)
		with patch(SUMMARY_CALL) as call:
			asyncio.run(run_agent_loop(adapter, system="s", user="u", tools=[tool], max_turns=20))
		call.assert_not_called()


class TestTheCodingAgentsAreSwitchedOn(FrappeTestCase):
	def test_the_patch_sets_the_threshold_once_and_keeps_a_chosen_value(self):
		agent = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": "Dev Agent",
				"agent_id": "dev_agent_loop_test",
				"agent_type": "Background",
				"agent_framework": "Direct API",
			}
		)
		if not frappe.db.exists("AI Agent Configuration", "Dev Agent"):
			agent.insert(ignore_permissions=True)
		frappe.db.set_value("AI Agent Configuration", "Dev Agent", "loop_compaction_threshold", 0)
		coding_agents_compact_their_tool_loop.execute()
		self.assertEqual(
			frappe.db.get_value(
				"AI Agent Configuration",
				"Dev Agent",
				["loop_compaction_threshold", "loop_compaction_keep_turns"],
			),
			(50000, 8),
		)
		frappe.db.set_value("AI Agent Configuration", "Dev Agent", "loop_compaction_threshold", 30000)
		coding_agents_compact_their_tool_loop.execute()
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", "Dev Agent", "loop_compaction_threshold"), 30000
		)

	def test_keeping_fewer_than_three_turns_is_refused(self):
		doc = frappe.new_doc("AI Agent Configuration")
		doc.loop_compaction_threshold = 50000
		doc.loop_compaction_keep_turns = 1
		with self.assertRaises(frappe.ValidationError):
			doc.validate_loop_compaction()
		doc.loop_compaction_keep_turns = 3
		doc.validate_loop_compaction()
