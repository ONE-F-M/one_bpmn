# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""WI-002195: every tool result the model sees is size-bounded, and every tool
call is checked against its declared schema before the script runs.

The audit copy (the ToolCallRecord, which becomes the AI Agent Tool Call row)
is never cut; only what goes back to the model is. A tool that declares no
parameters is never validated, so zero-argument tools keep working.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorConfig
from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.executor.tool_bounds import (
	DEFAULT_TOOL_RESULT_MAX_CHARS,
	MIN_TOOL_RESULT_MAX_CHARS,
	bound_tool_result,
	effective_max_chars,
	truncation_trailer,
	validate_tool_arguments,
)
from one_bpmn.agents.llm_provider.base import CompletionResult, StepResult, StepToolCall, ToolSpec
from one_bpmn.tests.test_ai_step_loop import FakeStepAdapter


def _run(adapter, tools, *, cap=None, resume=None, max_turns=10):
	return asyncio.run(
		run_agent_loop(
			adapter,
			system="sys",
			user="go",
			tools=tools,
			max_tokens=100,
			max_turns=max_turns,
			resume=resume,
			tool_result_max_chars=cap,
		)
	)


def _tool(name="lookup", fn=None, parameters=None, required=None):
	return ToolSpec(
		fn=fn or (lambda **kw: f"{name}-result"),
		name=name,
		description=f"{name} tool",
		parameters=parameters or {},
		required=required or [],
	)


def _call_then_answer(name, arguments):
	return FakeStepAdapter([
		StepResult(tool_calls=[StepToolCall(id="c1", name=name, arguments=arguments)]),
		StepResult(content="done"),
	])


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------


class TestBoundToolResult(FrappeTestCase):
	def test_under_the_cap_is_untouched(self):
		self.assertEqual(bound_tool_result("short", 1000), "short")
		exact = "x" * 1000
		self.assertEqual(bound_tool_result(exact, 1000), exact)

	def test_over_the_cap_is_cut_with_the_trailer(self):
		text = "a" * 1500
		out = bound_tool_result(text, 1000)
		self.assertTrue(out.startswith("a" * 1000))
		self.assertTrue(out.endswith(truncation_trailer(500)))
		self.assertIn("call again with a narrower request", out)

	def test_default_and_floor(self):
		self.assertEqual(effective_max_chars(None), DEFAULT_TOOL_RESULT_MAX_CHARS)
		self.assertEqual(effective_max_chars(0), DEFAULT_TOOL_RESULT_MAX_CHARS)
		self.assertEqual(effective_max_chars("junk"), DEFAULT_TOOL_RESULT_MAX_CHARS)
		self.assertEqual(effective_max_chars(10), MIN_TOOL_RESULT_MAX_CHARS)
		self.assertEqual(effective_max_chars(30000), 30000)

	def test_non_string_results_are_stringified_before_measuring(self):
		out = bound_tool_result({"k": "v" * 2000}, 1000)
		self.assertIn("truncated", out)


class TestCapInTheLoop(FrappeTestCase):
	def test_model_sees_a_bounded_copy_but_the_record_keeps_everything(self):
		big = "z" * 5000
		adapter = _call_then_answer("lookup", {})
		completion, _ = _run(adapter, [_tool(fn=lambda **kw: big)], cap=1000)

		sent = adapter.seen_transcripts[1][2]["results"][0]["content"]
		self.assertIn(truncation_trailer(4000), sent)
		self.assertNotIn("z" * 1001, sent)
		# The audit copy is the whole thing.
		self.assertEqual(completion.trace[0].tool_calls[0].result, big)

	def test_default_cap_applies_when_none_is_configured(self):
		big = "z" * (DEFAULT_TOOL_RESULT_MAX_CHARS + 10)
		adapter = _call_then_answer("lookup", {})
		_run(adapter, [_tool(fn=lambda **kw: big)])
		sent = adapter.seen_transcripts[1][2]["results"][0]["content"]
		self.assertIn(truncation_trailer(10), sent)

	def test_a_small_result_is_not_touched(self):
		adapter = _call_then_answer("lookup", {})
		_run(adapter, [_tool(fn=lambda **kw: "42")], cap=1000)
		sent = adapter.seen_transcripts[1][2]["results"][0]["content"]
		self.assertIn("42", sent)
		self.assertNotIn("truncated", sent)

	def test_the_human_answer_on_a_resumed_turn_is_bounded_too(self):
		adapter = FakeStepAdapter([StepResult(content="thanks")])
		resume = {
			"transcript": [{"role": "user", "content": "go"}],
			"pending_call": {"id": "h1", "name": "approval", "arguments": {}},
			"deferred_results": [],
			"turns_used": 1,
			"human_result": "y" * 3000,
		}
		_run(adapter, [_tool()], cap=1000, resume=resume)
		results = adapter.seen_transcripts[0][-1]["results"]
		self.assertIn(truncation_trailer(2000), results[0]["content"])


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestValidateToolArguments(FrappeTestCase):
	PARAMS = {
		"state": {"type": "string", "enum": ["Open", "Done"]},
		"limit": {"type": "integer"},
		"note": {"type": "string"},
	}

	def test_no_schema_means_no_check(self):
		self.assertIsNone(validate_tool_arguments("noop", {}, [], {"anything": 1}))
		self.assertIsNone(validate_tool_arguments("noop", None, None, None))

	def test_missing_required_argument_is_named(self):
		msg = validate_tool_arguments("wi_set_state", self.PARAMS, ["state"], {"note": "x"})
		self.assertEqual(msg, "Missing required argument 'state' for tool wi_set_state")

	def test_null_counts_as_missing(self):
		msg = validate_tool_arguments("wi_set_state", self.PARAMS, ["state"], {"state": None})
		self.assertEqual(msg, "Missing required argument 'state' for tool wi_set_state")

	def test_wrong_type_is_named(self):
		msg = validate_tool_arguments("search", self.PARAMS, [], {"limit": "ten"})
		self.assertEqual(msg, "Argument 'limit' for tool search must be integer, got string")

	def test_enum_violation_lists_the_choices(self):
		msg = validate_tool_arguments("wi_set_state", self.PARAMS, ["state"], {"state": "Closed"})
		self.assertEqual(msg, "Argument 'state' for tool wi_set_state must be one of: Open, Done")

	def test_valid_arguments_pass(self):
		self.assertIsNone(
			validate_tool_arguments("wi_set_state", self.PARAMS, ["state"], {"state": "Done", "limit": 3})
		)

	def test_undeclared_extra_arguments_are_tolerated(self):
		self.assertIsNone(validate_tool_arguments("search", self.PARAMS, [], {"limit": 1, "extra": "x"}))

	def test_arguments_must_be_an_object(self):
		msg = validate_tool_arguments("search", self.PARAMS, [], "limit=1")
		self.assertIn("must be a JSON object", msg)

	def test_array_items_are_checked(self):
		params = {"elements": {"type": "array", "items": {"type": "string"}}}
		msg = validate_tool_arguments("scan", params, ["elements"], {"elements": ["a", 2]})
		self.assertIn("scan", msg)
		self.assertIn("elements", msg)


class TestValidationInTheLoop(FrappeTestCase):
	def test_missing_argument_refuses_the_call_without_running_the_tool(self):
		ran = []

		def fn(**kw):
			ran.append(kw)
			return "changed"

		tool = _tool(
			"wi_set_state", fn=fn, parameters={"state": {"type": "string"}}, required=["state"]
		)
		adapter = _call_then_answer("wi_set_state", {"note": "please"})
		completion, _ = _run(adapter, [tool])

		self.assertEqual(ran, [])
		sent = adapter.seen_transcripts[1][2]["results"][0]["content"]
		self.assertIn("Missing required argument 'state' for tool wi_set_state", sent)
		# Recorded for the audit trail as the call's result.
		self.assertEqual(
			completion.trace[0].tool_calls[0].result,
			"Missing required argument 'state' for tool wi_set_state",
		)
		self.assertEqual(completion.text, "done")

	def test_a_valid_call_runs_as_before(self):
		ran = []
		tool = _tool(
			"wi_set_state",
			fn=lambda **kw: ran.append(kw) or "ok",
			parameters={"state": {"type": "string"}},
			required=["state"],
		)
		adapter = _call_then_answer("wi_set_state", {"state": "Done"})
		_run(adapter, [tool])
		self.assertEqual(ran, [{"state": "Done"}])

	def test_zero_argument_tools_are_never_validated(self):
		ran = []
		adapter = _call_then_answer("ping", {"unexpected": 1})
		_run(adapter, [_tool("ping", fn=lambda **kw: ran.append(kw) or "pong")])
		self.assertEqual(ran, [{"unexpected": 1}])

	def test_human_tools_are_not_validated(self):
		"""A human tool's arguments are for the person; the loop never runs it,
		so there is nothing to protect by refusing the call."""
		human = ToolSpec(
			fn=lambda **kw: None,
			name="approval",
			description="ask",
			parameters={"question": {"type": "string"}},
			required=["question"],
			human=True,
		)
		adapter = FakeStepAdapter([
			StepResult(tool_calls=[StepToolCall(id="h1", name="approval", arguments={})]),
		])
		completion, suspension = _run(adapter, [human])
		self.assertIsNone(completion)
		self.assertEqual(suspension.pending_call["name"], "approval")


# ---------------------------------------------------------------------------
# The cap travels from the configuration to the loop
# ---------------------------------------------------------------------------


class TestCapPlumbing(FrappeTestCase):
	def test_executor_config_carries_the_cap(self):
		self.assertIsNone(ExecutorConfig().tool_result_max_chars)
		self.assertEqual(ExecutorConfig(tool_result_max_chars=1234).tool_result_max_chars, 1234)

	def test_direct_api_hands_the_cap_to_the_loop(self):
		from one_bpmn.agents.executor.direct_api import DirectApiExecutor

		seen = {}

		async def fake_loop(adapter, **kwargs):
			seen.update(kwargs)
			return CompletionResult(text="ok", trace=[]), None

		config = ExecutorConfig(tools=[_tool()], tool_result_max_chars=777, max_tool_calls=3)
		with patch("one_bpmn.agents.executor.step_loop.run_agent_loop", fake_loop), \
			patch("one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=object()):
			DirectApiExecutor()._run_with_tools(config, "Anthropic", "sk-test", "claude-x")
		self.assertEqual(seen.get("tool_result_max_chars"), 777)

	def test_configuration_field_reaches_the_shape_overlay(self):
		from one_bpmn.agents.agent_config_resolver import config_field_map

		cfg = frappe._dict(
			ai_provider="Anthropic", ai_model="", context_max_messages=0, tool_result_max_chars=9000
		)
		with patch("frappe.db.exists", return_value=True), patch("frappe.get_doc", return_value=cfg):
			out = config_field_map("Probe Agent")
		self.assertEqual(out.get("aiToolResultMaxChars"), 9000)

	def test_zero_in_the_configuration_means_platform_default_not_zero(self):
		from one_bpmn.agents.agent_config_resolver import config_field_map

		cfg = frappe._dict(ai_provider="Anthropic", ai_model="", context_max_messages=0, tool_result_max_chars=0)
		with patch("frappe.db.exists", return_value=True), patch("frappe.get_doc", return_value=cfg):
			out = config_field_map("Probe Agent")
		self.assertNotIn("aiToolResultMaxChars", out)

	def test_the_field_exists_on_the_configuration_and_is_a_processa_control(self):
		from one_bpmn.api.security_api import AGENT_CONTROL_GROUPS

		self.assertTrue(frappe.get_meta("AI Agent Configuration").get_field("tool_result_max_chars"))
		fields = [f for _g, fs in AGENT_CONTROL_GROUPS for f in fs]
		self.assertIn("tool_result_max_chars", fields)
