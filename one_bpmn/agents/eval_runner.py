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
def run_eval_suite(suite_name: str, backend: str = "live") -> str:
    """
    Create an AI Eval Run for *suite_name* and enqueue its execution.

    backend="live" executes every case through the real executor.
    backend="replay" (WI-001364) re-runs assertion evaluation against each
    case's most recently stored actual_output without any new LLM call —
    free re-validation when an assertion or judge rubric changes. Replay
    deliberately does NOT mean deterministic LLM-response mocking (ruled
    out 2026-07-01): llm_judge assertions still make a real judge call and
    their cost is still counted — a known, accepted asymmetry.

    Returns the AI Eval Run name immediately; the cases run in a background
    job.
    """
    frappe.only_for("System Manager")

    if backend not in ("live", "replay"):
        frappe.throw(_("backend must be 'live' or 'replay', not '{0}'.").format(backend))

    if not frappe.db.exists("AI Eval Suite", suite_name):
        frappe.throw(_("AI Eval Suite '{0}' not found.").format(suite_name))

    run = frappe.new_doc("AI Eval Run")
    run.suite = suite_name
    run.status = "Running"
    run.backend = backend
    run.started_at = now_datetime()
    run.scope = "Suite"  # this entry point always runs the whole suite
    # The caller is already authorised above (suite read gate + evaluatable
    # check, or System Manager). The AI Eval Run is a system-written record of
    # that action, so it must not additionally demand write rights on the Run
    # doctype — a process owner may run their own suites without being able to
    # hand-edit run records.
    run.insert(ignore_permissions=True)

    frappe.enqueue(
        "one_bpmn.agents.eval_runner._execute_eval_suite",
        # WI-001365: eval suites share the dedicated AI queue so they never
        # compete with production business jobs for the default workers.
        queue="bpmn_ai_agent",
        run_name=run.name,
        timeout=1800,
    )

    return run.name


def _assert_agent_evaluatable(agent_cfg: str, eval_type: str) -> None:
    """Block a live run whose agent can't be evaluated, with a clear message
    (WI-001751). Only "Agent" (process) evals need a map — a Google ADK agent
    needs a process map to run and cannot be invoked standalone. "Direct" evals
    are a plain LLM call and work for any agent.
    """
    if not agent_cfg:
        frappe.throw(_("This suite has no agent configuration. Assign an agent before running evals."))
    if (eval_type or "Direct") != "Agent":
        return
    fw, pm = frappe.db.get_value(
        "AI Agent Configuration", agent_cfg, ["agent_framework", "process_model"]
    ) or (None, None)
    if (fw or "").strip().lower() == "google adk" and not pm:
        frappe.throw(_(
            "Agent '{0}' can't run an Agent (process) eval yet: it needs a process map. "
            "Give the agent a process map, or use a Direct eval suite instead."
        ).format(agent_cfg))


@frappe.whitelist()
def run_eval_cases(suite_name: str, case_names=None, backend: str = "live") -> str:
    """Run a chosen subset of a suite's cases (WI-001746), or the whole suite
    when no cases are given.

    Unlike ``run_eval_suite`` (System Manager only), this is available to any
    user who can read the suite — a process owner may run their own suites.
    The subset is validated to belong to the suite.
    """
    if backend not in ("live", "replay"):
        frappe.throw(_("backend must be 'live' or 'replay', not '{0}'.").format(backend))

    suite = frappe.get_doc("AI Eval Suite", suite_name)  # 404s if missing
    suite.check_permission("read")  # owner / System Manager gate

    if backend == "live":
        _assert_agent_evaluatable(suite.agent_configuration, suite.eval_type)

    if isinstance(case_names, str):
        case_names = frappe.parse_json(case_names) or None
    if case_names:
        valid = set(
            frappe.get_all("AI Eval Case", filters={"suite": suite_name}, pluck="name")
        )
        invalid = [c for c in case_names if c not in valid]
        if invalid:
            frappe.throw(_("Cases do not belong to this suite: {0}").format(", ".join(invalid)))
    else:
        case_names = None  # whole suite

    run = frappe.new_doc("AI Eval Run")
    run.suite = suite_name
    run.status = "Running"
    run.backend = backend
    run.started_at = now_datetime()
    # Record the requested scope now, so the run reports which cases it covers
    # even while Running, or if it errors before producing any result.
    run.scope = "Subset" if case_names else "Suite"
    run.requested_cases = json.dumps(case_names) if case_names else None
    # The caller is already authorised above (suite read gate + evaluatable
    # check, or System Manager). The AI Eval Run is a system-written record of
    # that action, so it must not additionally demand write rights on the Run
    # doctype — a process owner may run their own suites without being able to
    # hand-edit run records.
    run.insert(ignore_permissions=True)

    frappe.enqueue(
        "one_bpmn.agents.eval_runner._execute_eval_suite",
        queue="bpmn_ai_agent",
        run_name=run.name,
        case_names=case_names,
        timeout=1800,
    )
    return run.name


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _execute_eval_suite(run_name: str, case_names: list | None = None) -> None:
    """Run the suite's cases and finalise the AI Eval Run.

    ``case_names`` (WI-001746) restricts the run to a chosen subset; when None
    every case in the suite runs.

    WI-001361 Scenario 5: an unexpected exception partway through must
    never leave the Run stuck on "Running" — the run is finalised as
    status="Error" with whatever partial results were collected, and the
    completion event STILL fires so the client script's realtime listener
    doesn't hang forever.
    """
    run = frappe.get_doc("AI Eval Run", run_name)

    try:
        if case_names is None:
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
            if run.backend == "replay":
                result_row = _execute_case_replay(run, case)
            else:
                result_row = _execute_case(case)
            # Snapshot what was evaluated, so later edits to the case don't
            # rewrite this run's history. Set centrally so every path (live,
            # replay, error) records it.
            result_row.setdefault("input_user_prompt", case.input_user_prompt or "")
            result_row.setdefault("expected_output", case.expected_output or "")
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
    except Exception:
        frappe.log_error(
            title=f"AI Eval: suite execution failed ({run_name})",
            message=frappe.get_traceback(),
        )
        run.status = "Error"
        run.total_cases = len(run.results or [])
        run.passed_cases = sum(1 for r in (run.results or []) if r.status == "Passed")
        run.failed_cases = run.total_cases - run.passed_cases

    run.ended_at = now_datetime()
    # Background finalise: the job writes results on the user's behalf, so it
    # must not depend on that user holding write rights on AI Eval Run.
    run.save(ignore_permissions=True)
    # Background-job commit; skipped in tests so FrappeTestCase rollback
    # still cleans up fixture docs instead of leaking them into the DB.
    if not frappe.flags.in_test:
        frappe.db.commit()

    frappe.publish_realtime(
        "eval_run_completed",
        {"run_name": run.name, "status": run.status},
        user="all",
    )


def _execute_case_replay(run, case) -> dict:
    """
    Replay one case (WI-001364): skip the executor entirely and re-run
    evaluate-assertion logic against the case's most recent prior
    actual_output. total tokens/cost stay 0 for case execution; llm_judge
    assertions still make (and count) a real judge call.
    """
    prior = frappe.get_all(
        "AI Eval Result",
        filters={
            "eval_case": case.name,
            "parenttype": "AI Eval Run",
            "parent": ["!=", run.name],
        },
        fields=["actual_output", "status"],
        order_by="creation desc",
        limit_page_length=1,
    )
    if not prior:
        # Scenario 2: never run live — an explicit Error, not a silent skip
        # missing from the totals.
        return {
            "eval_case": case.name,
            "status": "Error",
            "error_message": "Nothing to replay: this case has no prior result. Run it live first.",
        }

    output = prior[0].actual_output or ""
    assertion_results = [
        _evaluate_assertion(assertion, output)
        for assertion in (case.assertions or [])
    ]
    all_passed = all(a["passed"] for a in assertion_results)
    any_errored = any(a.get("error") for a in assertion_results)

    # Judge calls still spend real tokens on replay (known asymmetry).
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
        "actual_output": output,
        "assertion_results": json.dumps(assertion_results, indent=4),
        "prompt_tokens": judge_prompt_tokens,
        "completion_tokens": judge_completion_tokens,
        "tokens_used": judge_prompt_tokens + judge_completion_tokens,
        "cost": judge_cost,
    }


def _execute_case(case) -> dict:
    """
    Evaluate a case against the suite's AI Agent Configuration (WI-001751).

    The suite's ``eval_type`` selects how the agent runs:
      - "Agent":  invoke the full agent through its process map (invoke_agent);
                  the AI Agent Runs it produces are tagged eval-origin and supply
                  the case's tokens/cost.
      - "Direct": a plain LLM call using the agent's provider/model/system prompt
                  (no map needed); a lightweight eval-origin AI Agent Run is
                  recorded so the call still shows in Insights.

    Any unexpected exception is captured as an Error result so the suite can
    continue.
    """
    try:
        agent_cfg = frappe.db.get_value("AI Eval Suite", case.suite, "agent_configuration")
        if not agent_cfg:
            return {
                "eval_case": case.name, "status": "Error",
                "error_message": "The suite has no agent configuration to test.",
            }
        eval_type = frappe.db.get_value("AI Eval Suite", case.suite, "eval_type") or "Direct"
        cfg = frappe.get_cached_doc("AI Agent Configuration", agent_cfg)

        if eval_type == "Agent":
            output, usage = _run_agent_eval(cfg, case)
        else:
            output, usage = _run_direct_eval(cfg, case)

        assertion_results = [
            _evaluate_assertion(assertion, output)
            for assertion in (case.assertions or [])
        ]
        all_passed = all(a["passed"] for a in assertion_results)
        any_errored = any(a.get("error") for a in assertion_results)

        judge_prompt_tokens = sum(a.get("judge_prompt_tokens", 0) for a in assertion_results)
        judge_completion_tokens = sum(a.get("judge_completion_tokens", 0) for a in assertion_results)
        judge_cost = sum(flt(a.get("judge_cost", 0)) for a in assertion_results)

        if any_errored:
            status = "Error"
        elif all_passed:
            status = "Passed"
        else:
            status = "Failed"

        # The split must add up to tokens_used: execution + judge on both sides.
        return {
            "eval_case": case.name,
            "status": status,
            "actual_output": _stringify(output),
            "assertion_results": json.dumps(assertion_results, indent=4),
            "prompt_tokens": usage["prompt_tokens"] + judge_prompt_tokens,
            "completion_tokens": usage["completion_tokens"] + judge_completion_tokens,
            "tokens_used": usage["tokens"] + judge_prompt_tokens + judge_completion_tokens,
            "cost": usage["cost"] + judge_cost,
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


def _run_agent_eval(cfg, case) -> tuple:
    """Agent (process) eval: invoke the full agent; tokens/cost from its runs.

    Returns ``(output, usage)`` where usage carries the prompt/completion split
    so the Result row's numbers add up.
    """
    from one_bpmn.api.agent_invocation import invoke_agent

    if not cfg.agent_id:
        raise ValueError(f"Agent configuration '{cfg.name}' has no agent_id.")

    context = {}
    if case.input_context:
        try:
            context = frappe.parse_json(case.input_context) or {}
        except Exception:
            context = {}

    started = now_datetime()
    prev = (getattr(frappe.flags, "eval_origin", None), getattr(frappe.flags, "bpmn_disable_ai_parking", False))
    frappe.flags.eval_origin = {"eval_case": case.name}
    frappe.flags.bpmn_disable_ai_parking = True
    try:
        reply = invoke_agent(cfg.agent_id, case.input_user_prompt or "", context=context)
    finally:
        frappe.flags.eval_origin, frappe.flags.bpmn_disable_ai_parking = prev

    output = (reply or {}).get("response") or ""
    runs = frappe.get_all(
        "AI Agent Run",
        filters={"agent_configuration": cfg.name, "creation": [">=", started]},
        fields=["total_prompt_tokens", "total_completion_tokens", "total_tokens", "estimated_cost"],
    )
    usage = {
        "prompt_tokens": sum((r.get("total_prompt_tokens") or 0) for r in runs),
        "completion_tokens": sum((r.get("total_completion_tokens") or 0) for r in runs),
        "tokens": sum((r.get("total_tokens") or 0) for r in runs),
        "cost": sum(flt(r.get("estimated_cost")) for r in runs),
    }
    return output, usage


def _run_direct_eval(cfg, case) -> tuple:
    """Direct (simple) eval: a plain LLM call with the agent's provider/model/
    system prompt. Records a standalone eval-origin AI Agent Run so the call
    shows in Insights alongside process (agent) evals."""
    provider = cfg.ai_provider_credentials or ""
    model = frappe.db.get_value("AI Provider Credentials", provider, "default_model") or ""

    started = now_datetime()
    config = ExecutorConfig(
        backend="direct_api",
        provider_name=provider,
        model=model,
        system_prompt=cfg.system_prompt or "",
        user_prompt=case.input_user_prompt or "",
    )
    result = get_executor("direct_api")().run(config, ExecutorContext())
    if result.error_code != ErrorCode.SUCCESS:
        raise RuntimeError(result.error_message or result.error_code.value)

    prompt_tokens = _prompt_tokens_of(result)
    completion_tokens = _completion_tokens_of(result)
    pricing = get_model_pricing(model)
    if not pricing:
        # Tokens are still counted; without an AI Model Pricing row the cost
        # would silently read $0.00, so leave a trace explaining why.
        frappe.log_error(
            title="AI Eval: no pricing for direct-eval model",
            message=f"No active AI Model Pricing for model '{model}' "
            f"(provider {provider}); cost recorded as 0 for case {case.name}.",
        )
        pricing = {}
    input_cost = (prompt_tokens / 1000.0) * flt(pricing.get("input_cost_per_1k", 0))
    output_cost = (completion_tokens / 1000.0) * flt(pricing.get("output_cost_per_1k", 0))

    try:
        frappe.get_doc({
            "doctype": "AI Agent Run",
            "bpmn_id": "direct-eval",
            "agent_configuration": cfg.name,
            "backend": "direct_api",
            "provider": provider,
            "model": model,
            "origin": "eval",
            "status": "Success",
            "started_at": started,
            "ended_at": now_datetime(),
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost": input_cost + output_cost,
            "total_input_cost": input_cost,
            "total_output_cost": output_cost,
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="AI Eval: direct-eval run record failed", message=frappe.get_traceback())

    return result.output, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens": prompt_tokens + completion_tokens,
        "cost": input_cost + output_cost,
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
