# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Running eval cases: the case entry point and each case's live, replay and deterministic execution."""

from __future__ import annotations

import json
from typing import List

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from processa.ai_agent_evals.runner.agent_eval import (
	eval_origin_flag,
	parked_calls,
	run_agent_eval,
	run_direct_eval,
)
from processa.ai_agent_evals.runner.assertions import (
	MODEL_BACKED_ASSERTIONS,
	evaluate_assertion,
	expected_tool_calls,
	stringify,
)
from processa.ai_agent_evals.runner.cases_memory import execute_memory_case
from processa.ai_agent_evals.runner.policy import (
	EVAL_BACKENDS,
	assert_agent_evaluatable,
	find_reusable_running_run,
	job_timeout,
	resolve_agent_configuration_fallback,
)


@frappe.whitelist(methods=["POST"])
def run_eval_cases(suite_name: str, case_names: list[str] | str | None = None, backend: str = "live") -> str:
    """Run a chosen subset of a suite's cases, or the whole suite
    when no cases are given.

    Unlike ``run_eval_suite`` (System Manager only), this is available to any
    user who can read the suite — a process owner may run their own suites.
    The subset is validated to belong to the suite.
    """
    if backend not in EVAL_BACKENDS:
        frappe.throw(_("backend must be one of {0}, not '{1}'.").format(", ".join(EVAL_BACKENDS), backend))

    suite = frappe.get_doc("AI Eval Suite", suite_name)  # 404s if missing
    suite.check_permission("read")  # owner / System Manager gate

    agent_cfg = resolve_agent_configuration_fallback(suite.agent_configuration, suite.process_model)
    if backend == "live":
        assert_agent_evaluatable(agent_cfg, suite.eval_type, suite.process_model)

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

    # One run at a time per suite (same agent, same backend): a second call
    # while one is still Running reuses it instead of starting a competitor.
    # Placed after the permission/evaluatable/case-validation gates above, so
    # a caller who cannot read the suite (or names a foreign case) fails
    # there, never reaching this dedup lookup.
    reusable = find_reusable_running_run(suite_name, agent_cfg, backend)
    if reusable:
        return reusable

    run = frappe.new_doc("AI Eval Run")
    run.suite = suite_name
    run.status = "Running"
    run.backend = backend
    run.started_at = now_datetime()
    # Record the requested scope now, so the run reports which cases it covers
    # even while Running, or if it errors before producing any result.
    run.scope = "Subset" if case_names else "Suite"
    run.requested_cases = json.dumps(case_names) if case_names else None
    run.agent_configuration = agent_cfg
    # The caller is already authorised above (suite read gate + evaluatable
    # check, or System Manager). The AI Eval Run is a system-written record of
    # that action, so it must not additionally demand write rights on the Run
    # doctype — a process owner may run their own suites without being able to
    # hand-edit run records.
    run.insert(ignore_permissions=True)  # perms: system-written run record; the caller was authorised above

    frappe.enqueue(
        "processa.ai_agent_evals.runner.suite.execute_eval_suite",
        queue="bpmn_ai_agent",
        run_name=run.name,
        case_names=case_names,
        fan_out=True,
        job_id=f"eval-run::{run.name}",
        deduplicate=True,
        timeout=job_timeout(
            suite_name, backend, len(case_names) if case_names else frappe.db.count("AI Eval Case", {"suite": suite_name})
        ),
    )
    return run.name


def _execute_case_deterministic(case) -> dict:
    """Score a case's assertions against the answer recorded on the case.

    No model is called, so this runs anywhere — a pull request check with no
    provider key included. What it proves is narrow, and worth stating: the
    assertions still hold against a known answer, so a change to an evaluator,
    an assertion, or the contract a prompt promises is caught before merge. It
    cannot prove the agent still produces that answer. That is the nightly live
    run's job.

    ``expected_output`` is the recorded answer. A case with none falls back to
    its last stored actual output, so a suite captured from real runs works here
    too.

    Assertions needing a model are SKIPPED, not failed. Failing them would turn
    "CI has no provider key" into a red check on every pull request; passing
    them would be a lie. They are reported, counted in neither column, and a
    case with nothing left to check is itself skipped.
    """
    answer = (case.expected_output or "").strip()
    source = "the case's recorded answer"
    borrowed = False
    if not answer:
        borrowed = True
        prior = frappe.get_all(
            "AI Eval Result",
            filters={"eval_case": case.name, "parenttype": "AI Eval Run"},
            fields=["actual_output"],
            order_by="creation desc",
            limit_page_length=1,
        )
        answer = (prior[0].actual_output or "").strip() if prior else ""
        source = "the last stored answer"

    assertions = case.assertions or []
    if not assertions:
        return _invalid_without_assertions(case)
    checkable = [a for a in assertions if a.assertion_type not in MODEL_BACKED_ASSERTIONS]
    needs_model = sorted({a.assertion_type for a in assertions if a.assertion_type in MODEL_BACKED_ASSERTIONS})

    if not answer:
        return {
            "eval_case": case.name,
            "status": "Skipped",
            "error_message": (
                "Nothing to score against: this case records no expected output and has never run. "
                "Give it the answer a deterministic check should hold to, or leave its suite out of Smoke."
            ),
        }

    if not checkable:
        return {
            "eval_case": case.name,
            "status": "Skipped",
            "actual_output": answer,
            "error_message": (
                "Every assertion here needs a model call (" + ", ".join(needs_model)
                + "), so a deterministic pass has nothing to check."
            ),
        }

    results = [evaluate_assertion(assertion, answer) for assertion in checkable]
    passed = all(r["passed"] for r in results)
    errored = any(r.get("error") for r in results)

    note = f"Scored against {source}, no model call."
    if needs_model:
        note += " Skipped " + ", ".join(needs_model) + " — needs a model."

    # The note is kept on a PASSING row too when the answer was borrowed from a
    # previous run: that a case has no recorded answer of its own is exactly the
    # thing a reader would otherwise never learn from a green result.
    worth_saying = errored or not passed or needs_model or borrowed

    return {
        "eval_case": case.name,
        "status": "Error" if errored else ("Passed" if passed else "Failed"),
        "actual_output": answer,
        "assertion_results": json.dumps(results, default=str),
        "error_message": note if worth_saying else "",
        "cost": 0,
        "tokens_used": 0,
    }


def _invalid_without_assertions(case) -> dict:
    """The row for a case with no assertions: nothing could make it fail, so it is not a pass."""
    return {
        "eval_case": case.name,
        "status": "Invalid",
        "error_message": _("This case has no assertions, so nothing can make it fail. Add one before it counts."),
    }


def execute_case_k_times(run_name: str, backend: str, case, agent_cfg: str | None, pass_k: int) -> dict:
    """Execute one case ``pass_k`` times and report how it behaved across them.

    A case that passes three times out of four is not a passing case: the fourth
    is what a user would have hit. So the row keeps the FAILING execution's
    output and assertions when there is one — a reviewer needs to see what went
    wrong, not the run that happened to go well — and reports the consistency
    rate beside it.

    Spend is summed over every execution, because every execution was billed.
    """
    attempts = []
    for _attempt in range(pass_k):
        if backend == "replay":
            attempts.append(_execute_case_replay(run_name, case))
        elif backend == "deterministic":
            attempts.append(_execute_case_deterministic(case))
        else:
            attempts.append(_execute_case(case, run_name, agent_cfg))

    passes = sum(1 for a in attempts if a.get("status") == "Passed")
    # The first execution that went wrong is the one worth reading; failing that,
    # the last good one.
    row = dict(next((a for a in attempts if a.get("status") != "Passed"), attempts[-1]))
    row["runs"] = len(attempts)
    row["passes"] = passes
    row["consistency_rate"] = passes / len(attempts) * 100
    row["status"] = "Passed" if passes == len(attempts) else row.get("status", "Failed")
    row["cost"] = sum(flt(a.get("cost")) for a in attempts)
    row["tokens_used"] = sum(cint(a.get("tokens_used")) for a in attempts)
    row["prompt_tokens"] = sum(cint(a.get("prompt_tokens")) for a in attempts)
    row["completion_tokens"] = sum(cint(a.get("completion_tokens")) for a in attempts)

    # A case that flipped says so on the row, so the failure reads as flakiness
    # rather than as a plain wrong answer.
    if 0 < passes < len(attempts):
        note = _("Flaky: passed {0} of {1} runs.").format(passes, len(attempts))
        row["error_message"] = f"{note}\n{row.get('error_message') or ''}".strip()

    return row


def _execute_case_replay(run_name: str, case) -> dict:
    """
    Replay one case: skip the executor entirely and re-run
    evaluate-assertion logic against the case's most recent prior
    actual_output. total tokens/cost stay 0 for case execution; llm_judge
    assertions still make (and count) a real judge call.
    """
    # Replay makes no execution call, but its llm_judge assertions still spend
    # real tokens through record_eval_run — stamp them with this case and run so
    # replay spend is attributable too.
    prev_origin = getattr(frappe.flags, "eval_origin", None)
    frappe.flags.eval_origin = eval_origin_flag(case, run_name)
    try:
        return _execute_case_replay_inner(run_name, case)
    finally:
        frappe.flags.eval_origin = prev_origin


def _execute_case_replay_inner(run_name: str, case) -> dict:
    """The body of ``_execute_case_replay``, with ``eval_origin`` already set."""
    prior = frappe.get_all(
        "AI Eval Result",
        filters={
            "eval_case": case.name,
            "parenttype": "AI Eval Run",
            "parent": ["!=", run_name],
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

    if not case.assertions:
        return _invalid_without_assertions(case)
    output = prior[0].actual_output or ""
    assertion_results = [
        evaluate_assertion(assertion, output)
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


def _execute_case(case, eval_run: str = None, agent_cfg: str = None) -> dict:
    """
    Evaluate a case against the suite's AI Agent Configuration.

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
    frappe.flags.eval_origin = eval_origin_flag(case, eval_run)
    try:
        result = _execute_case_inner(case, eval_run, agent_cfg)
        mark_expected_errors(case.name, case.get("expected_error"), eval_run)
        return result
    finally:
        frappe.flags.eval_origin = prev_origin


def mark_expected_errors(case_name: str, expected_error: str | None, eval_run: str | None = None) -> int:
    """Flag the case's step errors that contain ``expected_error`` so tool-error alerts skip them.

    ``eval_run`` limits it to one run; None covers every run of the case. Returns the count flagged.
    """
    expected = (expected_error or "").strip()
    if not expected:
        return 0
    run_filters = {"eval_case": case_name}
    if eval_run:
        run_filters["eval_run"] = eval_run
    runs = frappe.get_all("AI Agent Run", filters=run_filters, pluck="name")
    if not runs:
        return 0
    steps = frappe.get_all(
        "AI Agent Step",
        filters={"run": ["in", runs], "error_code": ["is", "set"], "is_expected_error": 0},
        fields=["name", "error_code", "error_message"],
    )
    flagged = [s.name for s in steps if expected in f"{s.error_code} {s.error_message or ''}"]
    for step_name in flagged:
        frappe.db.set_value("AI Agent Step", step_name, "is_expected_error", 1, update_modified=False)
    return len(flagged)


def _execute_case_inner(case, eval_run: str = None, agent_cfg: str = None) -> dict:
    """The body of ``_execute_case``, with ``frappe.flags.eval_origin`` already set.

    ``agent_cfg`` overrides the suite's own agent for this execution.
    The suite is left untouched — the override lives on the AI Eval Run.
    """
    try:
        # A memory case measures the memory pipeline, not the agent's answer, so
        # it needs no provider, no model and no map. Handled before the agent is
        # resolved for exactly that reason.
        if (case.get("case_type") or "") == "Memory":
            return execute_memory_case(case, eval_run)
        if not case.assertions:
            return _invalid_without_assertions(case)

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

        started = now_datetime()
        if eval_type == "Agent":
            output, usage = run_agent_eval(cfg, case, eval_run)
        else:
            output, usage = run_direct_eval(cfg, case)

        facts = _execution_facts(case, eval_run, usage, since=started)
        assertion_results = [
            evaluate_assertion(assertion, output, facts)
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
            "actual_output": stringify(output),
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


def _execution_facts(case, eval_run: str, usage: dict, since=None) -> dict:
    """What the assertions may know about the execution itself, not its text.

    ``since`` is when this execution started, so a pass_k repeat is scored on its own calls only."""
    trace = _tool_trace_for(case, eval_run, since)
    return {
        "tokens": cint(usage.get("tokens")),
        "tool_calls": [c["tool"] for c in trace],
        "tool_trace": trace,
        "expected_tool_calls": expected_tool_calls(case),
        "prompts": _prompts_for(case, eval_run, since),
    }


def _prompts_for(case, eval_run: str | None = None, since=None) -> list[str]:
    """The user prompts the case's runs sent to the model, which is where loaded skills are injected."""
    filters = {"eval_case": case.name}
    if eval_run:
        filters["eval_run"] = eval_run
    if since:
        filters["creation"] = [">=", since]
    runs = frappe.get_all("AI Agent Run", filters=filters, pluck="name")
    if not runs:
        return []
    return frappe.get_all("AI Agent Step", filters={"run": ["in", runs], "role": "user"}, pluck="content")


def _tool_trace_for(case, eval_run: str = None, since=None) -> List[dict]:
    """The calls this case made, in the order it made them, with their arguments.

    Order is the step's ``step_index`` and then the row's position within that
    step, which is the order the model asked for them. Reading the child rows
    without that ordering returns them in whatever order the database offers,
    which is exactly what an IN_ORDER assertion must not depend on.
    """
    filters = {"eval_case": case.name}
    if eval_run:
        filters["eval_run"] = eval_run
    if since:
        filters["creation"] = [">=", since]
    runs = frappe.get_all("AI Agent Run", filters=filters, pluck="name", order_by="creation asc")
    if not runs:
        return []
    steps = frappe.get_all(
        "AI Agent Step", filters={"run": ["in", runs]}, pluck="name", order_by="step_index asc, creation asc"
    )
    rows = frappe.get_all(
        "AI Agent Tool Call",
        filters={"parenttype": "AI Agent Step", "parent": ["in", steps]},
        fields=["parent", "idx", "tool_name", "tool_args", "status", "tool_artifact", "artifact_file"],
    ) if steps else []
    position = {name: index for index, name in enumerate(steps)}
    rows.sort(key=lambda r: (position.get(r["parent"], 0), cint(r["idx"])))

    trace = []
    for row in rows:
        try:
            args = frappe.parse_json(row["tool_args"]) if row["tool_args"] else {}
        except Exception:
            args = {}
        trace.append({
            "tool": row["tool_name"],
            "args": args if isinstance(args, dict) else {"": args},
            "status": row["status"],
            "artifact": row["tool_artifact"] or "",
            "artifact_file": row["artifact_file"],
        })
    # A parked call is the last thing the model did.
    return trace + parked_calls(runs)


def _tool_calls_for(case, eval_run: str = None) -> List[str]:
    """Tool names called while this case ran, read off the runs tagged with it."""
    filters = {"eval_case": case.name}
    if eval_run:
        filters["eval_run"] = eval_run
    runs = frappe.get_all("AI Agent Run", filters=filters, pluck="name")
    if not runs:
        return []
    steps = frappe.get_all("AI Agent Step", filters={"run": ["in", runs]}, pluck="name")
    called = frappe.get_all(
        "AI Agent Tool Call",
        filters={"parenttype": "AI Agent Step", "parent": ["in", steps]},
        pluck="tool_name",
    ) if steps else []
    return called + [call["tool"] for call in parked_calls(runs)]
