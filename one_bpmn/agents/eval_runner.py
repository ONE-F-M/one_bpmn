# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Eval runner — executes all cases in an AI Eval Suite via real LLM calls
and records per-case pass/fail results in an AI Eval Run.

Public API:
    run_eval_suite(suite_name) -> str   (whitelisted, returns run name)

Internal:
    _execute_eval_suite(run_name)       (background job on "long" queue)
"""
from __future__ import annotations

import inspect
import json
import re
from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.utils import now_datetime

from one_bpmn.agents.executor import (
	ErrorCode,
	ExecutorConfig,
	ExecutorContext,
	get_executor,
)


# ---------------------------------------------------------------------------
# Judge prompt template  (not configurable for v1)
# ---------------------------------------------------------------------------

JUDGE_PROMPT_TEMPLATE = """You are an evaluation judge. Score the following AI response based on the given rubric.

Rubric:
{rubric}

AI Response:
{actual_output}

Score the response from 1 to 5 where:
1 = Completely fails the rubric
5 = Fully meets the rubric

Respond with ONLY a JSON object:
{{"score": <int>, "explanation": "<one sentence>"}}"""


# ---------------------------------------------------------------------------
# Public whitelisted entry point
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_eval_suite(suite_name: str) -> str:
	"""
	Start an eval run for *suite_name*.

	Creates an AI Eval Run (status=Running), enqueues _execute_eval_suite
	on the "long" queue, and returns the run name immediately so the
	frontend can poll for progress.
	"""
	frappe.only_for("System Manager")

	if not frappe.db.exists("AI Eval Suite", suite_name):
		frappe.throw(
			_("AI Eval Suite {0} does not exist.").format(suite_name),
			frappe.DoesNotExistError,
		)

	run = frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite_name,
		"status": "Running",
		"backend": "live",
		"started_at": now_datetime(),
	})
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		method="one_bpmn.agents.eval_runner._execute_eval_suite",
		queue="long",
		timeout=1500,
		run_name=run.name,
	)

	return run.name


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _execute_eval_suite(run_name: str) -> None:
	"""
	Iterate through every case in the suite, call the executor, evaluate
	assertions, and record results. Finalises the AI Eval Run on completion.
	"""
	run = frappe.get_doc("AI Eval Run", run_name)

	cases = frappe.get_all(
		"AI Eval Case",
		filters={"suite": run.suite},
		fields=["name"],
		order_by="creation asc",
	)

	passed = 0
	failed = 0

	for case_row in cases:
		case = frappe.get_doc("AI Eval Case", case_row.name)

		try:
			result = _execute_single_case(case)
		except Exception as exc:
			result = {
				"status": "Error",
				"actual_output": "",
				"assertion_results": "[]",
				"error_message": str(exc),
				"tokens_used": 0,
				"cost": 0,
			}

		run.append("results", {
			"eval_case": case.name,
			"status": result["status"],
			"actual_output": result.get("actual_output", ""),
			"assertion_results": result.get("assertion_results", "[]"),
			"error_message": result.get("error_message", ""),
			"tokens_used": result.get("tokens_used", 0),
			"cost": result.get("cost", 0),
		})

		if result["status"] == "Passed":
			passed += 1
		else:
			failed += 1

	# ── Finalise ──────────────────────────────────────────────────────
	run.status = "Passed" if failed == 0 else "Failed"
	run.total_cases = len(cases)
	run.passed_cases = passed
	run.failed_cases = failed
	run.ended_at = now_datetime()
	run.save(ignore_permissions=True)
	frappe.db.commit()

	frappe.publish_realtime(
		event="eval_run_completed",
		message={"run_name": run.name},
	)


# ---------------------------------------------------------------------------
# Single-case execution
# ---------------------------------------------------------------------------

def _execute_single_case(case) -> Dict[str, Any]:
	"""
	Run the executor for *case* and evaluate all of its assertions.

	Returns a dict matching the AI Eval Result child-table fields.
	"""
	config = ExecutorConfig(
		backend=case.backend or "direct_api",
		provider_name=case.provider,
		model=case.model,
		system_prompt=case.input_system_prompt or "",
		user_prompt=case.input_user_prompt or "",
	)

	context = ExecutorContext()  # minimal context for evals

	executor_cls = get_executor(config.backend)
	executor = executor_cls()
	exec_result = executor.run(config, context)

	if exec_result.error_code != ErrorCode.SUCCESS:
		return {
			"status": "Error",
			"actual_output": str(exec_result.output or ""),
			"assertion_results": "[]",
			"error_message": exec_result.error_message,
			"tokens_used": _total_tokens(exec_result),
			"cost": 0,
		}

	output = str(exec_result.output or "")
	assertion_details = _evaluate_assertions(case.assertions or [], output)

	all_passed = all(a["passed"] for a in assertion_details)
	status = "Passed" if all_passed else "Failed"

	return {
		"status": status,
		"actual_output": output,
		"assertion_results": json.dumps(assertion_details),
		"error_message": "",
		"tokens_used": _total_tokens(exec_result),
		"cost": 0,
	}


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------

_ASSERTION_HANDLERS = {}


def _assertion_handler(assertion_type: str):
	"""Decorator to register an assertion evaluator."""
	def decorator(fn):
		_ASSERTION_HANDLERS[assertion_type] = fn
		return fn
	return decorator


def _evaluate_assertions(assertions, output: str) -> List[Dict[str, Any]]:
	"""
	Evaluate every assertion row against *output*.

	Returns a list of dicts.  Simple handlers return
	``{"type", "value", "passed", "message"}``.  The llm_judge handler
	additionally returns ``score`` and ``explanation``.

	Handlers may accept either ``(output, value)`` *or*
	``(output, value, assertion_row)``; the dispatcher introspects the
	function signature and passes the full row only when the handler
	expects three parameters.
	"""
	results = []
	for assertion in assertions:
		atype = assertion.assertion_type
		value = assertion.value or ""

		handler = _ASSERTION_HANDLERS.get(atype)
		if handler is None:
			results.append({
				"type": atype,
				"value": value,
				"passed": False,
				"message": f"Assertion type '{atype}' is not handled by this runner.",
			})
			continue

		# Extended handlers accept the full assertion row (3 params).
		sig = inspect.signature(handler)
		if len(sig.parameters) >= 3:
			result_dict = handler(output, value, assertion)
		else:
			passed, message = handler(output, value)
			result_dict = {
				"type": atype,
				"value": value,
				"passed": passed,
				"message": message,
			}

		# Ensure type/value are always present.
		result_dict.setdefault("type", atype)
		result_dict.setdefault("value", value)
		results.append(result_dict)

	return results


@_assertion_handler("contains")
def _assert_contains(output: str, value: str):
	"""Case-insensitive substring check."""
	passed = value.lower() in output.lower()
	message = "" if passed else f"Output does not contain '{value}'."
	return passed, message


@_assertion_handler("regex")
def _assert_regex(output: str, value: str):
	"""Regex search (re.search) against the output."""
	try:
		match = re.search(value, output)
		passed = match is not None
		message = "" if passed else f"Regex '{value}' did not match."
	except re.error as exc:
		passed = False
		message = f"Invalid regex pattern: {exc}"
	return passed, message


@_assertion_handler("equals")
def _assert_equals(output: str, value: str):
	"""Exact match after stripping whitespace."""
	passed = output.strip() == value.strip()
	message = "" if passed else "Output does not equal expected value."
	return passed, message


@_assertion_handler("schema_valid")
def _assert_schema_valid(output: str, value: str):
	"""Validate output as JSON against a JSON Schema."""
	try:
		parsed = json.loads(output)
	except json.JSONDecodeError as exc:
		return False, f"Output is not valid JSON: {exc}"

	try:
		import jsonschema
		schema = json.loads(value)
		jsonschema.validate(parsed, schema)
	except json.JSONDecodeError as exc:
		return False, f"Schema is not valid JSON: {exc}"
	except jsonschema.ValidationError as exc:
		return False, f"Schema validation failed: {exc.message}"

	return True, ""


@_assertion_handler("llm_judge")
def _assert_llm_judge(output: str, value: str, assertion_row) -> Dict[str, Any]:
	"""
	Call a judge LLM to score *output* against the rubric in *value*.

	Returns a result dict with type, passed, score, and explanation.
	"""
	judge_provider = getattr(assertion_row, "judge_provider", None) or ""
	judge_model = getattr(assertion_row, "judge_model", None) or ""
	pass_threshold = getattr(assertion_row, "pass_threshold", None)
	if pass_threshold is None or pass_threshold == 0:
		pass_threshold = 4

	# Build the judge prompt from the template constant.
	judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
		rubric=value,
		actual_output=output,
	)

	# Use the same executor infrastructure as the main agent call.
	config = ExecutorConfig(
		backend="direct_api",
		provider_name=judge_provider,
		model=judge_model,
		system_prompt="",
		user_prompt=judge_prompt,
		response_format="json",
	)
	context = ExecutorContext()

	try:
		executor_cls = get_executor(config.backend)
		executor = executor_cls()
		exec_result = executor.run(config, context)
	except Exception as exc:
		return {
			"type": "llm_judge",
			"passed": False,
			"score": 0,
			"explanation": f"Judge call failed: {exc}",
		}

	if exec_result.error_code != ErrorCode.SUCCESS:
		return {
			"type": "llm_judge",
			"passed": False,
			"score": 0,
			"explanation": f"Judge call failed: {exec_result.error_message}",
		}

	# Parse the judge response as JSON.
	raw_output = exec_result.output
	if isinstance(raw_output, dict):
		judge_data = raw_output
	else:
		try:
			judge_data = json.loads(str(raw_output))
		except (json.JSONDecodeError, TypeError, ValueError):
			return {
				"type": "llm_judge",
				"passed": False,
				"score": 0,
				"explanation": "Judge returned invalid JSON",
			}

	score = judge_data.get("score", 0)
	explanation = judge_data.get("explanation", "")

	try:
		score = int(score)
	except (TypeError, ValueError):
		score = 0

	passed = score >= pass_threshold

	return {
		"type": "llm_judge",
		"passed": passed,
		"score": score,
		"explanation": explanation,
	}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _total_tokens(exec_result) -> int:
	"""Extract total token count from an ExecutorResult."""
	if exec_result.token_usage:
		return exec_result.token_usage.total_tokens
	return 0
