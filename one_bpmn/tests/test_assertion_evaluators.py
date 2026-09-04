# Copyright (c) 2026, one-fm and contributors
# WI-001362 (5-02): assertion evaluators for all five assertion types.
# Gap closure against the evaluators already merged on staging: judge/
# assertion failures must surface as ERROR (never silently Passed/Failed),
# and llm_judge's own token spend must reach the Result's totals.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import eval_runner
from one_bpmn.agents.eval_runner import _evaluate_assertion

test_ignore = ["AI Eval Suite", "AI Eval Case"]


def _assertion(assertion_type, value, **extra):
	return SimpleNamespace(
		assertion_type=assertion_type,
		value=value,
		judge_provider=extra.get("judge_provider", ""),
		judge_model=extra.get("judge_model", ""),
		pass_threshold=extra.get("pass_threshold", 4),
	)


class TestAssertionEvaluators(FrappeTestCase):
	# ── Scenario 2: contains / regex / equals ──

	def test_contains(self):
		self.assertTrue(_evaluate_assertion(_assertion("contains", "world"), "Hello World")["passed"])
		self.assertFalse(_evaluate_assertion(_assertion("contains", "mars"), "Hello World")["passed"])

	def test_regex(self):
		self.assertTrue(_evaluate_assertion(_assertion("regex", r"\d{3}"), "code 123")["passed"])
		self.assertFalse(_evaluate_assertion(_assertion("regex", r"^\d+$"), "abc")["passed"])

	def test_equals(self):
		self.assertTrue(_evaluate_assertion(_assertion("equals", "yes"), " yes ")["passed"])
		self.assertFalse(_evaluate_assertion(_assertion("equals", "yes"), "no")["passed"])

	# ── Scenario 1: schema_valid ──

	def test_schema_valid(self):
		schema = '{"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}'
		self.assertTrue(_evaluate_assertion(_assertion("schema_valid", schema), '{"a": 1}')["passed"])
		bad = _evaluate_assertion(_assertion("schema_valid", schema), '{"a": "not int"}')
		self.assertFalse(bad["passed"])
		self.assertTrue(bad.get("message"))

	# ── Scenario 5: bad assertion → Error result, suite keeps going ──

	def test_invalid_regex_is_error_not_failed(self):
		result = _evaluate_assertion(_assertion("regex", "([unclosed"), "text")
		self.assertFalse(result["passed"])
		self.assertTrue(result.get("error"))

	def test_unsupported_type_is_error(self):
		result = _evaluate_assertion(_assertion("telepathy", "x"), "text")
		self.assertTrue(result.get("error"))

	# ── Scenarios 3/4: llm_judge scoring, failure = Error, cost counted ──

	def _judge_executor(self, output=None, error=False):
		from one_bpmn.agents.executor import (
			ErrorCode,
			ExecutorResult,
			TokenUsage,
		)

		class FakeJudge:
			def run(self, config, context):
				if error:
					return ExecutorResult(
						error_code=ErrorCode.FAILED_MODEL_CALL, error_message="judge down"
					)
				return ExecutorResult(
					output=output,
					token_usage=TokenUsage(prompt_tokens=40, completion_tokens=8, total_tokens=48),
				)

		return patch.object(eval_runner, "get_executor", return_value=FakeJudge)

	def test_llm_judge_passes_at_threshold(self):
		with self._judge_executor(output='{"score": 5, "explanation": "great"}'):
			result = _evaluate_assertion(_assertion("llm_judge", "Is it polite?"), "output")
		self.assertTrue(result["passed"])
		self.assertEqual(result["score"], 5)
		self.assertEqual(result["judge_prompt_tokens"], 40)
		self.assertEqual(result["judge_completion_tokens"], 8)

	def test_llm_judge_fails_below_threshold(self):
		with self._judge_executor(output='{"score": 2, "explanation": "rude"}'):
			result = _evaluate_assertion(_assertion("llm_judge", "Is it polite?"), "output")
		self.assertFalse(result["passed"])
		self.assertFalse(result.get("error", False))

	def test_llm_judge_call_failure_is_error(self):
		with self._judge_executor(error=True):
			result = _evaluate_assertion(_assertion("llm_judge", "rubric"), "output")
		self.assertTrue(result.get("error"))
		self.assertFalse(result["passed"])

	def test_llm_judge_unparseable_score_is_error(self):
		with self._judge_executor(output="not json at all {{{"):
			result = _evaluate_assertion(_assertion("llm_judge", "rubric"), "output")
		self.assertTrue(result.get("error"))

	# ── Case-level: Error status propagation + judge cost in totals ──

	def test_case_with_errored_assertion_is_error_and_counts_judge_tokens(self):
		from one_bpmn.agents.executor import ExecutorResult, TokenUsage

		case = SimpleNamespace(
			name="case-x",
			backend="direct_api",
			provider="",
			model="m",
			input_system_prompt="",
			input_user_prompt="p",
			assertions=[_assertion("llm_judge", "rubric")],
		)

		class FakeCaseExecutor:
			def run(self, config, context):
				return ExecutorResult(
					output="case output",
					token_usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
				)

		def fake_get_executor(backend):
			return FakeCaseExecutor

		judge_result = {
			"assertion_type": "llm_judge",
			"value": "rubric",
			"passed": False,
			"error": True,
			"judge_prompt_tokens": 40,
			"judge_completion_tokens": 8,
			"judge_cost": 0.002,
			"score": 0,
			"explanation": "Judge call failed: down",
		}
		with (
			patch.object(eval_runner, "get_executor", side_effect=fake_get_executor),
			patch.object(eval_runner, "_evaluate_assertion", return_value=judge_result),
		):
			row = eval_runner._execute_case(case)

		self.assertEqual(row["status"], "Error")
		self.assertEqual(row["prompt_tokens"], 140)
		self.assertEqual(row["completion_tokens"], 28)
		self.assertEqual(row["tokens_used"], 168)
		self.assertAlmostEqual(row["cost"], 0.002)


class TestExecutionAssertions(FrappeTestCase):
	"""max_tokens and no_tool_call judge the run, not the answer text.

	A greeting that quietly ran the schema writer reads exactly like one that
	did not — only the token count and the tool calls tell them apart, and
	neither is in the output the other assertion types see.
	"""

	def test_token_ceiling(self):
		facts = {"tokens": 480, "tool_calls": []}
		self.assertTrue(_evaluate_assertion(_assertion("max_tokens", "500"), "hi", facts)["passed"])
		over = _evaluate_assertion(_assertion("max_tokens", "300"), "hi", facts)
		self.assertFalse(over["passed"])
		self.assertIn("480", over["message"])

	def test_token_ceiling_needs_a_number(self):
		result = _evaluate_assertion(_assertion("max_tokens", "cheap"), "hi", {"tokens": 10})
		self.assertTrue(result.get("error"))

	def test_forbidden_tool_that_ran_fails_the_case(self):
		facts = {"tokens": 10, "tool_calls": ["classify_intent", "write_schema"]}
		result = _evaluate_assertion(_assertion("no_tool_call", "write_schema,review_schema"), "hi", facts)
		self.assertFalse(result["passed"])
		self.assertIn("write_schema", result["message"])

	def test_other_tools_are_allowed(self):
		"""Only the named tools are forbidden — the stage that recognises a
		greeting has to run for the greeting to be recognised."""
		facts = {"tokens": 10, "tool_calls": ["classify_intent"]}
		self.assertTrue(
			_evaluate_assertion(_assertion("no_tool_call", "write_schema"), "hi", facts)["passed"]
		)

	def test_forbidden_list_cannot_be_empty(self):
		result = _evaluate_assertion(_assertion("no_tool_call", "  "), "hi", {"tool_calls": []})
		self.assertTrue(result.get("error"))

	def test_a_replay_says_it_cannot_measure_instead_of_passing(self):
		"""Replay re-reads a stored answer, so there is no execution to measure.
		Silently passing would make a re-check look like proof."""
		for a_type, value in (("max_tokens", "500"), ("no_tool_call", "write_schema")):
			result = _evaluate_assertion(_assertion(a_type, value), "hi")
			self.assertFalse(result["passed"], a_type)
			self.assertTrue(result.get("error"), a_type)

	def test_tool_calls_are_read_off_the_runs_tagged_with_the_case(self):
		"""Tool calls sit two levels down (Run -> Step -> Tool Call) and only the
		eval_case/eval_run tags connect them to the case that paid for them."""
		run = frappe.get_doc({
			"doctype": "AI Agent Run",
			"bpmn_id": "run_docu_agent",
			"origin": "eval",
			"eval_case": "greeting-case",
			"eval_run": "greeting-run",
			"status": "Success",
			"started_at": frappe.utils.now_datetime(),
			# The tags are Links; this run stands in for a case and run that a
			# real eval would have created around it.
		}).insert(ignore_permissions=True, ignore_links=True)
		step = frappe.get_doc({
			"doctype": "AI Agent Step",
			"run": run.name,
			"step_index": 1,
			"role": "assistant",
			"content": "",
		})
		step.append("tool_calls", {"tool_name": "write_schema", "status": "Success"})
		step.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "AI Agent Step", step.name, force=True)
		self.addCleanup(frappe.delete_doc, "AI Agent Run", run.name, force=True)

		case = SimpleNamespace(name="greeting-case")
		self.assertEqual(eval_runner._tool_calls_for(case, "greeting-run"), ["write_schema"])
		facts = eval_runner._execution_facts(case, "greeting-run", {"tokens": 1484})
		self.assertEqual(facts["tokens"], 1484)
		self.assertFalse(
			_evaluate_assertion(_assertion("no_tool_call", "write_schema"), "hi", facts)["passed"]
		)

	def test_another_cases_tools_are_not_counted(self):
		case = SimpleNamespace(name="a-case-that-never-ran")
		self.assertEqual(eval_runner._tool_calls_for(case, "some-run"), [])
