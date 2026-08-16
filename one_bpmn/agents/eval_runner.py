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

# bpmn_id markers for the eval LLM calls recorded as AI Agent Runs (origin="eval").
EVAL_RUN_DIRECT = "direct-eval"
EVAL_RUN_JUDGE = "eval-judge"

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
    # WI-001821: record which agent this run tested. Without it a later
    # comparison has to assume the suite still points where it did at run time.
    run.agent_configuration = frappe.db.get_value(
        "AI Eval Suite", suite_name, "agent_configuration"
    )
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


def _assert_agent_evaluatable(agent_cfg: str, eval_type: str, suite_map: str = "") -> None:
    """Block a live run whose agent can't be evaluated, with a clear message
    (WI-001751). Only "Agent" (process) evals need a map — a Google ADK agent
    needs a process map to run and cannot be invoked standalone. "Direct" evals
    are a plain LLM call and work for any agent.

    ``suite_map`` is the map the suite itself names. When set, the run takes the
    map path (see ``_run_map_eval``), which starts that map directly instead of
    going through the agent's own chat map — so the agent not having one of its
    own is no longer a blocker.
    """
    if not agent_cfg:
        frappe.throw(_("This suite has no agent configuration. Assign an agent before running evals."))
    if (eval_type or "Direct") != "Agent":
        return
    if (suite_map or "").strip():
        return
    fw, pm = frappe.db.get_value(
        "AI Agent Configuration", agent_cfg, ["agent_framework", "process_model"]
    ) or (None, None)
    if (fw or "").strip().lower() == "google adk" and not pm:
        frappe.throw(_(
            "Agent '{0}' can't run an Agent (process) eval yet: it needs a process map. "
            "Give the agent a process map, name one on the suite, or use a Direct eval "
            "suite instead."
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
        _assert_agent_evaluatable(
            suite.agent_configuration, suite.eval_type, suite.process_model
        )

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
    run.agent_configuration = suite.agent_configuration  # WI-001821
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
# A/B comparison (WI-001821)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_eval_comparison(
    suite_name: str,
    agent_b: str,
    agent_a: str = None,
    case_names=None,
    backend: str = "live",
) -> dict:
    """Run one suite against two agents and return both AI Eval Runs.

    This is the answer to "which of these two agents should I ship?" — the same
    cases, the same assertions, executed twice, once per agent. Neither run
    touches the suite: the agent each one tested is recorded on the RUN
    (``agent_configuration``), so the suite stays bound to whatever it was bound
    to before and after. Duplicating the suite would work too, but duplicates
    drift and then the comparison means nothing.

    The two runs share a ``comparison_group``; that is how the comparison view
    finds the other side.

    The case list is FROZEN here rather than resolved per run. Both sides must
    execute exactly the same cases for the comparison to say anything, and a
    case added between the two runs starting would otherwise appear on one side
    only.

    ``agent_a`` defaults to the suite's own agent — the usual "is the challenger
    better than what I have?" shape.

    Returns both run names immediately; the cases run in background jobs.
    """
    if backend not in ("live", "replay"):
        frappe.throw(_("backend must be 'live' or 'replay', not '{0}'.").format(backend))

    suite = frappe.get_doc("AI Eval Suite", suite_name)  # 404s if missing
    suite.check_permission("read")  # same gate as run_eval_cases

    agent_a = agent_a or suite.agent_configuration
    if not agent_a:
        frappe.throw(
            _(
                "This suite has no agent, so there is nothing to compare against. "
                "Assign one, or nominate both sides explicitly."
            )
        )
    if agent_a == agent_b:
        frappe.throw(
            _("Both sides name the same agent ('{0}') — a comparison needs two.").format(agent_a)
        )
    for agent in (agent_a, agent_b):
        if not frappe.db.exists("AI Agent Configuration", agent):
            frappe.throw(_("AI Agent Configuration '{0}' not found.").format(agent))
        if backend == "live":
            _assert_agent_evaluatable(agent, suite.eval_type, suite.process_model)

    # Freeze the case list, and validate a requested subset the same way
    # run_eval_cases does.
    if isinstance(case_names, str):
        case_names = frappe.parse_json(case_names) or None
    suite_cases = frappe.get_all(
        "AI Eval Case", filters={"suite": suite_name}, pluck="name", order_by="creation asc"
    )
    if case_names:
        invalid = [c for c in case_names if c not in set(suite_cases)]
        if invalid:
            frappe.throw(_("Cases do not belong to this suite: {0}").format(", ".join(invalid)))
        scope = "Subset"
    else:
        case_names = suite_cases
        scope = "Suite"

    if not case_names:
        frappe.throw(
            _("This suite has no cases, so a comparison would compare nothing. Add a case first.")
        )

    group = frappe.generate_hash(length=12)
    runs = []
    for agent in (agent_a, agent_b):
        run = frappe.new_doc("AI Eval Run")
        run.suite = suite_name
        run.agent_configuration = agent
        run.comparison_group = group
        run.status = "Running"
        run.backend = backend
        run.started_at = now_datetime()
        run.scope = scope
        # Always recorded, even for a whole-suite comparison: it is the frozen
        # list both sides ran, and it is what makes the two provably comparable
        # later even if the suite gains cases in between.
        run.requested_cases = json.dumps(case_names)
        # System-written record of an action the caller is already authorised
        # for — see run_eval_cases.
        run.insert(ignore_permissions=True)
        runs.append(run.name)

    for run_name in runs:
        frappe.enqueue(
            "one_bpmn.agents.eval_runner._execute_eval_suite",
            queue="bpmn_ai_agent",
            run_name=run_name,
            case_names=case_names,
            timeout=1800,
        )

    return {
        "comparison_group": group,
        "run_a": runs[0],
        "run_b": runs[1],
        "agent_a": agent_a,
        "agent_b": agent_b,
        "total_cases": len(case_names),
    }


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
        # WI-001821: a run may nominate an agent other than the suite's, so an
        # A/B comparison never has to rebind the suite. Resolved once here
        # rather than per case, so every case in a run is judged against the
        # same agent even if the suite is reassigned mid-run.
        agent_cfg = run.get("agent_configuration") or None
        for case_name in case_names:
            case = frappe.get_doc("AI Eval Case", case_name)
            if run.backend == "replay":
                result_row = _execute_case_replay(run, case)
            else:
                result_row = _execute_case(case, run.name, agent_cfg)
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
    # Replay makes no execution call, but its llm_judge assertions still spend
    # real tokens through _record_eval_run — stamp them with this case and run so
    # replay spend is attributable too.
    prev_origin = getattr(frappe.flags, "eval_origin", None)
    frappe.flags.eval_origin = _eval_origin_flag(case, run.name)
    try:
        return _execute_case_replay_inner(run, case)
    finally:
        frappe.flags.eval_origin = prev_origin


def _execute_case_replay_inner(run, case) -> dict:
    """The body of ``_execute_case_replay``, with ``eval_origin`` already set."""
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


def _eval_origin_flag(case, eval_run: str = None) -> dict:
    """The ``frappe.flags.eval_origin`` payload for one case's execution.

    Both creators of eval-origin AI Agent Runs read it — ``observability.create_ai_run``
    for the agent's own runs, and ``_record_eval_run`` for the direct call and each
    judge call — so the back-links cannot drift between them.
    """
    return {"eval_case": case.name, "eval_run": eval_run or ""}


def _execute_case(case, eval_run: str = None, agent_cfg: str = None) -> dict:
    """
    Evaluate a case against the suite's AI Agent Configuration (WI-001751).

    The suite's ``eval_type`` selects how the agent runs:
      - "Agent":  run the full agent through its process map, so its tools run
                  too. When the case or suite names a ``process_model`` that map
                  is started directly (the only path that works for a Background
                  or otherwise non-chat agent); otherwise the turn goes through
                  the chat-shaped ``invoke_agent``. Either way the AI Agent Runs
                  produced are tagged eval-origin and supply tokens/cost.
      - "Direct": a plain LLM call using the agent's provider/model/system prompt
                  (no map needed, and NO tools); a lightweight eval-origin AI
                  Agent Run is recorded so the call still shows in Insights.

    Any unexpected exception is captured as an Error result so the suite can
    continue.

    ``eval_origin`` is set for the WHOLE case, not just the agent call, so the
    judge calls made while evaluating assertions are stamped with the same case
    and run as the execution they are judging.
    """
    prev_origin = getattr(frappe.flags, "eval_origin", None)
    frappe.flags.eval_origin = _eval_origin_flag(case, eval_run)
    try:
        return _execute_case_inner(case, eval_run, agent_cfg)
    finally:
        frappe.flags.eval_origin = prev_origin


def _execute_case_inner(case, eval_run: str = None, agent_cfg: str = None) -> dict:
    """The body of ``_execute_case``, with ``frappe.flags.eval_origin`` already set.

    ``agent_cfg`` overrides the suite's own agent for this execution (WI-001821).
    The suite is left untouched — the override lives on the AI Eval Run.
    """
    try:
        agent_cfg = agent_cfg or frappe.db.get_value(
            "AI Eval Suite", case.suite, "agent_configuration"
        )
        if not agent_cfg:
            return {
                "eval_case": case.name, "status": "Error",
                "error_message": "The suite has no agent configuration to test.",
            }
        eval_type = frappe.db.get_value("AI Eval Suite", case.suite, "eval_type") or "Direct"
        cfg = frappe.get_cached_doc("AI Agent Configuration", agent_cfg)

        if eval_type == "Agent":
            output, usage = _run_agent_eval(cfg, case, eval_run)
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


def _cost_split(prompt_tokens: int, completion_tokens: int, model: str) -> tuple:
    """(input_cost, output_cost) for a call, from AI Model Pricing."""
    pricing = get_model_pricing(model) or {}
    return (
        (prompt_tokens / 1000.0) * flt(pricing.get("input_cost_per_1k", 0)),
        (completion_tokens / 1000.0) * flt(pricing.get("output_cost_per_1k", 0)),
    )


def _record_eval_run(
    bpmn_id: str,
    provider: str,
    model: str,
    started,
    prompt_tokens: int,
    completion_tokens: int,
    input_cost: float,
    output_cost: float,
    agent_configuration: str = None,
) -> None:
    """Record an eval LLM call as an AI Agent Run tagged origin="eval".

    Evals spend real money outside the BPMN AI Agent Task path: the direct-eval
    call and every llm_judge assertion. Recording them keeps AI Agent Runs the
    single ledger of all AI cost, so cost reporting reads one place and can never
    double-count evals. Never raises — failing to record usage must not fail the
    eval itself.
    """
    origin = getattr(frappe.flags, "eval_origin", None)
    if not isinstance(origin, dict):
        origin = {}
    ended = now_datetime()
    try:
        elapsed_ms = int((ended - started).total_seconds() * 1000) if started else 0
    except Exception:
        elapsed_ms = 0
    try:
        frappe.get_doc({
            "doctype": "AI Agent Run",
            "bpmn_id": bpmn_id,
            "agent_configuration": agent_configuration,
            # Same linkage as the agent's own runs, so the direct call and every
            # judge call are attributable to the case that paid for them.
            "eval_case": origin.get("eval_case") or None,
            "eval_run": origin.get("eval_run") or None,
            "backend": "direct_api",
            "provider": provider or "",
            "model": model or "",
            "origin": "eval",
            "status": "Success",
            "started_at": started,
            "ended_at": ended,
            # WI-001821: an eval call is a single provider round-trip with no
            # human wait and no inter-step gap, so its wall time IS the agent
            # latency WI-001643 defines. Leaving these unset made every eval-origin
            # run report "latency not measured", which is what an A/B comparison
            # most needs to show.
            "duration_ms": elapsed_ms,
            "agent_latency_ms": elapsed_ms,
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost": input_cost + output_cost,
            "total_input_cost": input_cost,
            "total_output_cost": output_cost,
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(
            title=f"AI Eval: run record failed ({bpmn_id})",
            message=frappe.get_traceback(),
        )


def _map_is_chat_startable(model_name: str) -> bool:
    """True when *model_name*'s start event triggers on Chat Conversation.

    ``invoke_agent`` can only drive such a map: it delivers the turn to an
    instance already running for the conversation it just created, and only a
    Chat-Conversation start event produces one.
    """
    if not model_name:
        return False
    xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml") or ""
    return 'triggerDoctype="Chat Conversation"' in xml


def _needs_map_eval(cfg) -> bool:
    """True when this agent cannot be driven through the chat-shaped eval path.

    A Background agent has no chat map by definition, and a Chat agent whose
    linked map is record-triggered is in the same position — ``invoke_agent``
    throws "not running for this conversation" for both. An agent with no map at
    all keeps today's legacy single-shot behaviour, so existing suites that rely
    on it are unaffected.
    """
    if (cfg.get("agent_type") or "Chat") == "Background":
        return True
    linked = (cfg.get("process_model") or "").strip()
    return bool(linked) and not _map_is_chat_startable(linked)


def _eval_map_for_case(cfg, case) -> str:
    """The map a map-path eval starts: the case's, else the suite's, else the
    agent's own. Naming it on the case lets one suite cover several maps."""
    for candidate in (
        (case.process_model or "").strip(),
        (frappe.db.get_value("AI Eval Suite", case.suite, "process_model") or "").strip(),
        (cfg.get("process_model") or "").strip(),
    ):
        if candidate:
            return candidate
    return ""


def _eval_context_document(case) -> tuple:
    """The document a map eval runs against, read from the case's input_context.

    A record-triggered map takes its subject from the instance context — the
    shape's prompts render ``{{ doc.* }}`` against it and its start condition is
    evaluated on it — so the case names one::

        {"context_doctype": "Leave Application", "context_docname": "HR-LAP-2026-00586"}

    A case captured from a real run needs no such hand-editing: it already links
    its ``source_run``, whose instance recorded the document the agent ran
    against, so that is used when input_context does not name one. Explicit
    input_context always wins, so a captured case can be re-pointed by editing it.
    """
    ctx = {}
    if case.input_context:
        try:
            ctx = frappe.parse_json(case.input_context) or {}
        except Exception:
            ctx = {}
    if not isinstance(ctx, dict):
        ctx = {}
    doctype = (ctx.get("context_doctype") or "").strip()
    docname = (ctx.get("context_docname") or "").strip()
    if doctype and docname:
        return doctype, docname

    source_run = (case.get("source_run") or "").strip()
    if source_run:
        instance = frappe.db.get_value("AI Agent Run", source_run, "instance")
        if instance:
            row = frappe.db.get_value(
                "BPMN Process Instance", instance,
                ["context_doctype", "context_docname"], as_dict=True,
            )
            if row and row.context_doctype and row.context_docname:
                return row.context_doctype, row.context_docname
    return "", ""


def _run_map_eval(cfg, case) -> tuple:
    """Agent eval for an agent whose map is not chat-startable.

    ``invoke_agent`` is chat-shaped: it mints a Chat Conversation and hands the
    turn to an ALREADY-RUNNING instance, so it can only drive a map whose start
    event triggers on Chat Conversation. A Background agent — or any agent whose
    map is record-triggered — has no such map, which left its tools (the shapes
    of its AI Agent Task's ad-hoc sub-process) impossible to exercise from an
    eval: the Agent path threw, and the Direct path never attaches tools at all.

    This path starts the map the case names, against the document the case names,
    exactly as the record trigger would, then reads back the AI Agent Run the
    pass produced. Tool calls land on that Run's Steps, so the transcript shows
    which tools were called with which arguments.

    The caller has already set ``frappe.flags.bpmn_disable_ai_parking``, so the
    AI work runs INLINE rather than being enqueued to ``bpmn_ai_agent`` — the Run
    and its tool calls exist by the time ``instance.start()`` returns.
    """
    model_name = _eval_map_for_case(cfg, case)
    if not model_name:
        raise ValueError(
            f"Agent '{cfg.name}' has no chat-startable map, so its Agent eval must be "
            f"told which process map to run. Name one on the case or on the suite "
            f"(process_model)."
        )
    doctype, docname = _eval_context_document(case)
    if not doctype or not docname:
        raise ValueError(
            f"Case runs process map '{model_name}', so it must name the document to run "
            'against — either input_context {"context_doctype": "…", "context_docname": '
            '"…"}, or a source_run whose instance recorded one.'
        )
    if not frappe.db.exists(doctype, docname):
        raise ValueError(
            f"No {doctype} named '{docname}' — check the case's input_context."
        )

    instance = frappe.new_doc("BPMN Process Instance")
    instance.process_model = model_name
    instance.context_doctype = doctype
    instance.context_docname = docname
    instance.status = "Active"
    instance.initiated_by = frappe.session.user
    instance.started_at = now_datetime()
    instance.insert(ignore_permissions=True)

    try:
        instance.start(
            initial_data={
                "triggered_by": frappe.session.user,
                "trigger_doctype": doctype,
                "trigger_docname": docname,
            }
        )
    finally:
        # An eval must never leave a live instance parked on a human task. The
        # AI Agent Run — with its Steps and tool calls — is a separate record and
        # survives cancellation, so the transcript stays reviewable.
        if frappe.db.get_value("BPMN Process Instance", instance.name, "status") == "Active":
            frappe.db.set_value(
                "BPMN Process Instance", instance.name, "status", "Cancelled",
                update_modified=False,
            )

    filters = {"instance": instance.name}
    if case.bpmn_id:
        filters["bpmn_id"] = case.bpmn_id
    else:
        # Judge runs carry no instance, but be explicit rather than rely on that.
        filters["bpmn_id"] = ["!=", EVAL_RUN_JUDGE]
    runs = frappe.get_all(
        "AI Agent Run",
        filters=filters,
        fields=["final_output", "total_prompt_tokens", "total_completion_tokens",
                "total_tokens", "estimated_cost"],
        order_by="creation asc",
    )
    if not runs:
        shape = f" for shape '{case.bpmn_id}'" if case.bpmn_id else ""
        raise ValueError(
            f"Process map '{model_name}' ran but produced no AI Agent Run{shape}. Check "
            f"that the map reaches its AI Agent Task for this document — a conditional "
            f"start event that does not match leaves the process with nothing to do."
        )

    # The last run is the agent's answer; earlier ones (retries, other AI shapes)
    # still count toward spend.
    output = runs[-1].get("final_output") or ""
    usage = {
        "prompt_tokens": sum((r.get("total_prompt_tokens") or 0) for r in runs),
        "completion_tokens": sum((r.get("total_completion_tokens") or 0) for r in runs),
        "tokens": sum((r.get("total_tokens") or 0) for r in runs),
        "cost": sum(flt(r.get("estimated_cost")) for r in runs),
    }
    return output, usage


def _run_agent_eval(cfg, case, eval_run: str = None) -> tuple:
    """Agent (process) eval: run the full agent; tokens/cost from its runs.

    Two shapes, chosen by whether the agent can be driven through chat:
      - non-chat agent (Background, or a record-triggered map) -> ``_run_map_eval``
        starts the named map directly. The only path that exercises their tools.
      - chat agent -> ``invoke_agent``, the chat-shaped path, unchanged.

    Returns ``(output, usage)`` where usage carries the prompt/completion split
    so the Result row's numbers add up.
    """
    prev = (
        getattr(frappe.flags, "eval_origin", None),
        getattr(frappe.flags, "bpmn_disable_ai_parking", False),
    )
    frappe.flags.eval_origin = _eval_origin_flag(case, eval_run)
    frappe.flags.bpmn_disable_ai_parking = True
    try:
        if _needs_map_eval(cfg):
            return _run_map_eval(cfg, case)
        return _run_chat_agent_eval(cfg, case)
    finally:
        frappe.flags.eval_origin, frappe.flags.bpmn_disable_ai_parking = prev


def _run_chat_agent_eval(cfg, case) -> tuple:
    """The chat-shaped Agent eval: hand the turn to ``invoke_agent``.

    Only drives a map whose start event triggers on Chat Conversation; for
    anything else use ``_run_map_eval``. Eval flags are set by the caller.
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
    reply = invoke_agent(cfg.agent_id, case.input_user_prompt or "", context=context)

    output = (reply or {}).get("response") or ""
    runs = frappe.get_all(
        "AI Agent Run",
        filters={
            "agent_configuration": cfg.name,
            "creation": [">=", started],
            # Judge runs are recorded separately and their cost is added by
            # _execute_case; excluding them here keeps execution and judge spend
            # from being counted twice on the Result row.
            "bpmn_id": ["!=", EVAL_RUN_JUDGE],
        },
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
    # WI-001655: the MODEL is the agent's own catalog pick and the credentials
    # record carries the connection only — default_model was removed from that
    # doctype. Reading it here did one of two wrong things depending on whether
    # the site's column survived the field removal: returned a stale orphan
    # value (so the eval silently tested a model the agent does not use, and
    # priced the run against it), or raised Unknown column, turning every
    # Direct case into an Error result. Either way the agent's real model was
    # never exercised.
    #
    # Last-resort fallback mirrors DirectApiExecutor: any catalog model linked
    # to these credentials, for a legacy agent with no ai_model set.
    model = cfg.get("ai_model") or frappe.db.get_value(
        "AI Model", {"ai_provider_credentials": provider}, "name"
    ) or ""

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

    _record_eval_run(
        EVAL_RUN_DIRECT, provider, model, started,
        prompt_tokens, completion_tokens, input_cost, output_cost,
        agent_configuration=cfg.name,
    )

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

    judge_started = now_datetime()
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
    judge_prompt_tokens = _prompt_tokens_of(judge_result)
    judge_completion_tokens = _completion_tokens_of(judge_result)
    judge_in_cost, judge_out_cost = _cost_split(
        judge_prompt_tokens, judge_completion_tokens, judge_config.model
    )
    judge_usage = {
        "judge_prompt_tokens": judge_prompt_tokens,
        "judge_completion_tokens": judge_completion_tokens,
        "judge_cost": judge_in_cost + judge_out_cost,
    }
    # The judge is a billed LLM call of its own. Record it in the AI Agent Run
    # ledger too (it never goes through an AI Agent Task), so cost reporting
    # built on runs is not missing judge spend. Recorded even when the judge
    # errored, as long as it consumed tokens.
    if judge_prompt_tokens or judge_completion_tokens:
        _record_eval_run(
            EVAL_RUN_JUDGE,
            judge_config.provider_name,
            judge_config.model,
            judge_started,
            judge_prompt_tokens,
            judge_completion_tokens,
            judge_in_cost,
            judge_out_cost,
        )

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


