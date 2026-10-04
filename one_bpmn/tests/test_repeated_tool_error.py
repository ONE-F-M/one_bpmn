# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A run stops with REPEATED_TOOL_ERROR when one tool fails the same way twice in a row."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec

MISS = json.dumps({"error": "old_string not found in the file"})


def _provider(name):
	if not frappe.db.exists("AI Provider", name):
		frappe.get_doc({"doctype": "AI Provider", "provider": name}).insert(ignore_permissions=True)
	return name


def _model(name):
	if not frappe.db.exists("AI Model", name):
		frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": name,
				"provider": _provider("Anthropic"),
				"enable_model": 1,
				"api_key": "test-key-not-real",
			}
		).insert(ignore_permissions=True)
	return name


class _EditLoopAdapter:
	"""Asks for one edit_file call every turn."""

	def __init__(self):
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384, **_):
		self.calls += 1
		call = StepToolCall(id=f"c{self.calls}", name="edit_file", arguments={"path": "a.py"})
		return StepResult(content="", tool_calls=[call], prompt_tokens=100, completion_tokens=10)


def _run(results):
	"""Run the loop with an edit_file tool that answers each call with the next of results."""
	answers = iter(results)
	tool = ToolSpec(
		fn=lambda **kw: next(answers),
		name="edit_file",
		description="Edit a file.",
		parameters={"path": {"type": "string", "description": "Path"}},
		required=["path"],
	)
	config = ExecutorConfig(
		provider_name=_provider("Anthropic"),
		model=_model("_repeat-model"),
		system_prompt="sys",
		user_prompt="usr",
		tools=[tool],
		max_tool_calls=len(results),
	)
	adapter = _EditLoopAdapter()
	with patch("one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=adapter):
		result = DirectApiExecutor().run(config, ExecutorContext())
	return result, adapter


class TestTheLoopStopsOnARepeatedError(FrappeTestCase):
	def test_two_identical_errors_end_the_run(self):
		result, adapter = _run([MISS, MISS, MISS, MISS])

		self.assertEqual(result.error_code, ErrorCode.REPEATED_TOOL_ERROR)
		self.assertEqual(adapter.calls, 2)
		self.assertIn("edit_file failed twice in a row", result.error_message)
		self.assertIn("old_string not found", result.error_message)

	def test_a_different_error_does_not_end_the_run(self):
		other = json.dumps({"error": "old_string appears 2 times"})
		result, adapter = _run([MISS, other, MISS, other])

		self.assertEqual(result.error_code, ErrorCode.TURN_CAP_REACHED)
		self.assertEqual(adapter.calls, 4)

	def test_a_success_in_between_resets_the_count(self):
		ok = json.dumps({"edited": True})
		result, adapter = _run([MISS, ok, MISS, ok])

		self.assertEqual(result.error_code, ErrorCode.TURN_CAP_REACHED)
		self.assertEqual(adapter.calls, 4)
