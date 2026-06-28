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
from frappe.utils import now_datetime

from one_bpmn.agents.executor import (
    ErrorCode,
    ExecutorConfig,
    ExecutorContext,
    get_executor,
)
# Importing the backend modules registers them in the executor registry.
from one_bpmn.agents.executor.direct_api import DirectApiExecutor  # noqa: F401
from one_bpmn.agents.executor.antigravity import AntigravityExecutor  # noqa: F401


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
    for case_name in case_names:
        case = frappe.get_doc("AI Eval Case", case_name)
        result_row = _execute_case(case)
        run.append("results", result_row)
        if result_row["status"] == "Passed":
            passed += 1
        else:
            failed += 1

    run.total_cases = len(case_names)
    run.passed_cases = passed
    run.failed_cases = failed
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
                "tokens_used": _tokens_of(result),
                "cost": _cost_of(result),
            }

        output = result.output
        assertion_results = [
            _evaluate_assertion(assertion, output)
            for assertion in (case.assertions or [])
        ]
        all_passed = all(a["passed"] for a in assertion_results)

        return {
            "eval_case": case.name,
            "status": "Passed" if all_passed else "Failed",
            "actual_output": _stringify(output),
            "assertion_results": json.dumps(assertion_results),
            "tokens_used": _tokens_of(result),
            "cost": _cost_of(result),
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
            # Handled by story 6-05; not evaluated by the live runner yet.
            return {**base, "passed": False,
                    "message": "llm_judge assertions are not evaluated by this runner."}

        return {**base, "passed": False,
                "message": f"Unsupported assertion type: {a_type!r}."}
    except Exception as exc:
        return {**base, "passed": False, "message": f"Assertion error: {exc}"}


def _evaluate_schema_valid(schema_str: str, output: Any) -> dict:
    """Pass if *output* is valid JSON that validates against *schema_str*."""
    import jsonschema

    # The output may already be a parsed object (json response_format) or a
    # JSON string (text response_format).
    if isinstance(output, str):
        try:
            instance = json.loads(output)
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


def _cost_of(result) -> float:
    # No per-token pricing is configured on AI Provider yet, so cost is
    # recorded as 0.0. Kept as a seam for when pricing data is added.
    return 0.0
