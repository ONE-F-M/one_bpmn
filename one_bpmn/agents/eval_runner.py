# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
agents/eval_runner — the "live" eval backend.

run_eval_suite(suite_name) is the whitelisted entry point. It creates an
AI Eval Run in the "Running" state and enqueues the actual work to the
"long" queue, returning the run name immediately.

_execute_eval_suite(run_name) is the background job. It iterates the suite's
cases, calls the configured executor backend with each case's prompts (real
LLM calls), evaluates the case's assertions against the output, and records
one AI Eval Result child row per case. When finished it finalises the run
(status, counts, ended_at) and publishes an "eval_run_completed" realtime
event.

A single failing/erroring case never aborts the suite — its result is
recorded and the runner moves on.
"""
from __future__ import annotations

import json
import re
from typing import Any, List

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from one_bpmn.agents.executor import (
    ErrorCode,
    ExecutorConfig,
    ExecutorContext,
    get_executor,
)
# Importing the backend modules registers them in the executor registry.
from one_bpmn.agents.executor.direct_api import (  # noqa: F401
    DirectApiExecutor,
    _strip_code_fences,
)
from one_bpmn.agents.executor.antigravity import AntigravityExecutor  # noqa: F401
from one_bpmn.agents.pricing import get_model_pricing


# ---------------------------------------------------------------------------
# LLM Judge prompt template (not configurable for v1)
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
# Whitelisted entry point
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_eval_suite(suite_name: str) -> str:
    """
    Create an AI Eval Run for *suite_name* and enqueue its execution.

    Returns the AI Eval Run name immediately; the cases run in a background
    job on the "long" queue.
    """
    frappe.only_for("System Manager")

    if not frappe.db.exists("AI Eval Suite", suite_name):
        frappe.throw(_("AI Eval Suite '{0}' not found.").format(suite_name))

    run = frappe.new_doc("AI Eval Run")
    run.suite = suite_name
    run.status = "Running"
    run.backend = "live"
    run.started_at = now_datetime()
    run.insert()

    frappe.enqueue(
        "one_bpmn.agents.eval_runner._execute_eval_suite",
        queue="long",
        run_name=run.name,
        timeout=1800,
    )
    
    return run.name


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _execute_eval_suite(run_name: str) -> None:
    """Run every case in the suite and finalise the AI Eval Run."""
    run = frappe.get_doc("AI Eval Run", run_name)

    case_names = frappe.get_all(
        "AI Eval Case",
        filters={"suite": run.suite},
        pluck="name",
        order_by="creation asc",
    )

    passed = failed = 0
    total_cost = 0.0
    total_tokens = 0
    for case_name in case_names:
        case = frappe.get_doc("AI Eval Case", case_name)
        result_row = _execute_case(case)
        run.append("results", result_row)
        if result_row["status"] == "Passed":
            passed += 1
        else:
            failed += 1
        total_cost += flt(result_row.get("cost", 0))
        total_tokens += (result_row.get("tokens_used") or 0)

    run.total_cases = len(case_names)
    run.passed_cases = passed
    run.failed_cases = failed
    run.total_cost = total_cost
    run.total_tokens = total_tokens
    run.status = "Passed" if failed == 0 else "Failed"
    run.ended_at = now_datetime()
    run.save()
    frappe.db.commit()

    frappe.publish_realtime(
        "eval_run_completed",
        {"run_name": run.name, "status": run.status},
        user="all",
    )


def _execute_case(case) -> dict:
    """
    Run a single case through its executor and evaluate its assertions.

    Returns a dict suitable for appending to AI Eval Run.results. Any
    unexpected exception is captured as an Error result so the suite can
    continue.
    """
    try:
        config = ExecutorConfig(
            backend=case.backend or "direct_api",
            provider_name=case.provider or "",
            model=case.model or "",
            system_prompt=case.input_system_prompt or "",
            user_prompt=case.input_user_prompt or "",
        )
        # Evals carry no instance and no context document — just the prompts.
        context = ExecutorContext()

        executor_cls = get_executor(config.backend)
        result = executor_cls().run(config, context)

        if result.error_code != ErrorCode.SUCCESS:
            return {
                "eval_case": case.name,
                "status": "Error",
                "error_message": result.error_message
                or result.error_code.value,
                "prompt_tokens": _prompt_tokens_of(result),
                "completion_tokens": _completion_tokens_of(result),
                "tokens_used": _tokens_of(result),
                "cost": _cost_of(result, config.model),
            }

        output = result.output
        assertion_results = [
            _evaluate_assertion(assertion, output)
            for assertion in (case.assertions or [])
        ]
        all_passed = all(a["passed"] for a in assertion_results)
        any_errored = any(a.get("error") for a in assertion_results)

        # WI-001362: judge calls spend their own tokens — add them to the
        # Result separately from the case's executor call so the Run-level
        # rollup doesn't undercount.
        judge_prompt_tokens = sum(a.get("judge_prompt_tokens", 0) for a in assertion_results)
        judge_completion_tokens = sum(a.get("judge_completion_tokens", 0) for a in assertion_results)
        judge_cost = sum(flt(a.get("judge_cost", 0)) for a in assertion_results)

        if any_errored:
            status = "Error"
        elif all_passed:
            status = "Passed"
        else:
            status = "Failed"

        return {
            "eval_case": case.name,
            "status": status,
            "actual_output": _stringify(output),
            "assertion_results": json.dumps(assertion_results, indent=4),
            "prompt_tokens": _prompt_tokens_of(result) + judge_prompt_tokens,
            "completion_tokens": _completion_tokens_of(result) + judge_completion_tokens,
            "tokens_used": _tokens_of(result) + judge_prompt_tokens + judge_completion_tokens,
            "cost": _cost_of(result, config.model) + judge_cost,
        }
    except Exception:
        frappe.log_error(
            title=f"AI Eval: case execution failed ({case.name})",
            message=frappe.get_traceback(),
        )
        return {
            "eval_case": case.name,
            "status": "Error",
            "error_message": frappe.get_traceback(),
        }


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------

def _evaluate_assertion(assertion, output: Any) -> dict:
    """
    Evaluate one assertion against *output*.

    Returns a dict {assertion_type, value, passed, message} describing the
    outcome. Evaluation never raises — a malformed assertion (e.g. a bad
    regex) is reported as a non-passing result.
    """
    a_type = assertion.assertion_type
    value = assertion.value or ""
    base = {"assertion_type": a_type, "value": value}

    try:
        if a_type == "contains":
            passed = value.strip().lower() in _stringify(output).lower()
            return {**base, "passed": passed,
                    "message": "" if passed else "Substring not found."}

        if a_type == "regex":
            passed = bool(re.search(value, _stringify(output)))
            return {**base, "passed": passed,
                    "message": "" if passed else "Pattern did not match."}

        if a_type == "equals":
            passed = _stringify(output).strip() == value.strip()
            return {**base, "passed": passed,
                    "message": "" if passed else "Output did not equal expected value."}

        if a_type == "schema_valid":
            return {**base, **_evaluate_schema_valid(value, output)}

        if a_type == "llm_judge":
            return _evaluate_llm_judge(assertion, output)

        return {**base, "passed": False, "error": True,
                "message": f"Unsupported assertion type: {a_type!r}."}
    except Exception as exc:
        # WI-001362 Scenario 5: a bad assertion (e.g. invalid regex) is an
        # ERROR result — never silently Passed/Failed, never a crash that
        # aborts the other cases in the suite.
        return {**base, "passed": False, "error": True,
                "message": f"Assertion error: {exc}"}


def _evaluate_schema_valid(schema_str: str, output: Any) -> dict:
    """Pass if *output* is valid JSON that validates against *schema_str*."""
    import jsonschema

    # The output may already be a parsed object (json response_format) or a
    # JSON string (text response_format).
    if isinstance(output, str):
        try:
            instance = json.loads(_strip_code_fences(output))
        except json.JSONDecodeError as exc:
            return {"passed": False, "message": f"Output is not valid JSON: {exc}"}
    else:
        instance = output

    try:
        schema = json.loads(schema_str)
    except json.JSONDecodeError as exc:
        return {"passed": False, "message": f"Schema is not valid JSON: {exc}"}

    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError as exc:
        return {"passed": False, "message": f"Schema validation failed: {exc.message}"}

    return {"passed": True, "message": ""}


def _evaluate_llm_judge(assertion, output: Any) -> dict:
    """
    Call a judge LLM to score *output* against the rubric in *assertion.value*.

    Uses the same executor infrastructure as the main agent call. Returns a
    dict with type, passed, score, and explanation.
    """
    a_type = assertion.assertion_type
    value = assertion.value or ""
    base = {"assertion_type": a_type, "value": value}

    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        rubric=value,
        actual_output=_stringify(output),
    )

    judge_config = ExecutorConfig(
        backend="direct_api",
        provider_name=assertion.judge_provider or "",
        model=assertion.judge_model or "",
        system_prompt="",
        user_prompt=judge_prompt,
        response_format="json",
    )
    judge_context = ExecutorContext()

    try:
        executor_cls = get_executor(judge_config.backend)
        judge_result = executor_cls().run(judge_config, judge_context)
    except Exception as exc:
        # WI-001362 Scenario 4: a failed judge call is an ERROR, never
        # silently Passed or Failed.
        return {
            **base,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": f"Judge call failed: {exc}",
        }

    # The judge call spends real tokens of its own (WI-001362 note): report
    # them on the assertion so _execute_case can add them to the Result's
    # token/cost fields — otherwise the Run-level rollup undercounts.
    judge_usage = {
        "judge_prompt_tokens": _prompt_tokens_of(judge_result),
        "judge_completion_tokens": _completion_tokens_of(judge_result),
        "judge_cost": _cost_of(judge_result, judge_config.model),
    }

    if judge_result.error_code != ErrorCode.SUCCESS:
        return {
            **base,
            **judge_usage,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": f"Judge call failed: {judge_result.error_message}",
        }

    # Parse the judge response — it may already be a dict (json response_format)
    # or a raw string.
    judge_output = judge_result.output
    if isinstance(judge_output, str):
        try:
            judge_output = json.loads(_strip_code_fences(judge_output))
        except (json.JSONDecodeError, TypeError):
            return {
                **base,
                **judge_usage,
                "passed": False,
                "error": True,
                "score": 0,
                "explanation": "Judge returned invalid JSON",
            }

    if not isinstance(judge_output, dict):
        return {
            **base,
            **judge_usage,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": "Judge returned invalid JSON",
        }

    try:
        score = int(judge_output.get("score", 0))
    except (ValueError, TypeError):
        return {
            **base,
            **judge_usage,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": "Judge returned invalid JSON",
        }

    explanation = str(judge_output.get("explanation", ""))
    threshold = assertion.pass_threshold or 4
    passed = score >= threshold

    return {
        **base,
        **judge_usage,
        "passed": passed,
        "score": score,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stringify(output: Any) -> str:
    """Render executor output as text for substring/regex/equals assertions."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output)


def _tokens_of(result) -> int:
    return result.token_usage.total_tokens if result.token_usage else 0


def _prompt_tokens_of(result) -> int:
    return result.token_usage.prompt_tokens if result.token_usage else 0


def _completion_tokens_of(result) -> int:
    return result.token_usage.completion_tokens if result.token_usage else 0


def _cost_of(result, model: str = "") -> float:
    """Compute cost from AI Model Pricing, mirroring observability.record_ai_step."""
    if not result.token_usage or not model:
        return 0.0

    pricing = get_model_pricing(model)
    if not pricing:
        return 0.0

    input_rate = flt(pricing.get("input_cost_per_1k", 0))
    output_rate = flt(pricing.get("output_cost_per_1k", 0))
    input_cost = (result.token_usage.prompt_tokens / 1000.0) * input_rate
    output_cost = (result.token_usage.completion_tokens / 1000.0) * output_rate
    return input_cost + output_cost
