# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The eval suite entry point and the background job that runs a suite."""

from __future__ import annotations

import threading

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from processa.ai_agent_evals.runner.lanes import execute_lanes, fan_out_eval_suite
from processa.ai_agent_evals.runner.policy import (
	EVAL_BACKENDS,
	eval_concurrency,
	find_reusable_running_run,
	job_timeout,
	resolve_agent_configuration_fallback,
	suite_run_status,
)


@frappe.whitelist(methods=["POST"])
def run_eval_suite(suite_name: str, backend: str = "live") -> str:
    """
    Create an AI Eval Run for *suite_name* and enqueue its execution.

    backend="live" executes every case through the real executor.
    backend="replay" re-runs assertion evaluation against each
    case's most recently stored actual_output without any new LLM call —
    free re-validation when an assertion or judge rubric changes. Replay
    deliberately does NOT mean deterministic LLM-response mocking (ruled
    out 2026-07-01): llm_judge assertions still make a real judge call and
    their cost is still counted — a known, accepted asymmetry.

    Returns the AI Eval Run name immediately; the cases run in a background
    job.
    """
    frappe.only_for("System Manager")

    if backend not in EVAL_BACKENDS:
        frappe.throw(_("backend must be one of {0}, not '{1}'.").format(", ".join(EVAL_BACKENDS), backend))

    if not frappe.db.exists("AI Eval Suite", suite_name):
        frappe.throw(_("AI Eval Suite '{0}' not found.").format(suite_name))

    # record which agent this run tested. Without it a later
    # comparison has to assume the suite still points where it did at run time.
    agent_cfg = resolve_agent_configuration_fallback(
        *frappe.db.get_value("AI Eval Suite", suite_name, ["agent_configuration", "process_model"])
    )

    # One run at a time per suite (same agent, same backend): a second call
    # while one is still Running reuses it instead of starting a competitor.
    reusable = find_reusable_running_run(suite_name, agent_cfg, backend)
    if reusable:
        return reusable

    run = frappe.new_doc("AI Eval Run")
    run.suite = suite_name
    run.status = "Running"
    run.backend = backend
    run.started_at = now_datetime()
    run.scope = "Suite"  # this entry point always runs the whole suite
    run.agent_configuration = agent_cfg
    # The caller is already authorised above (suite read gate + evaluatable
    # check, or System Manager). The AI Eval Run is a system-written record of
    # that action, so it must not additionally demand write rights on the Run
    # doctype — a process owner may run their own suites without being able to
    # hand-edit run records.
    run.insert(ignore_permissions=True)  # perms: system-written run record; the caller was authorised above

    frappe.enqueue(
        "processa.ai_agent_evals.runner.suite.execute_eval_suite",
        # eval suites share the dedicated AI queue so they never
        # compete with production business jobs for the default workers.
        queue="bpmn_ai_agent",
        run_name=run.name,
        fan_out=True,
        job_id=f"eval-run::{run.name}",
        deduplicate=True,
        timeout=job_timeout(suite_name, backend, frappe.db.count("AI Eval Case", {"suite": suite_name})),
    )

    return run.name


def execute_eval_suite(run_name: str, case_names: list | None = None, fan_out: bool = False) -> None:
    """Run the suite's cases and finalise the AI Eval Run.

    ``case_names`` restricts the run to a chosen subset; when None
    every case in the suite runs.

    ``fan_out=False`` (the default) is the original, synchronous behaviour:
    this call runs every lane inline (in threads, above a concurrency of one)
    and returns only once the run is fully finalised. ``adversarial_gate`` and
    ``eval_ci`` depend on exactly this — they call this function directly and
    read ``run.results`` the moment it returns.

    ``fan_out=True`` is used by the whitelisted entry points
    (``run_eval_suite``, ``run_eval_cases``, ``run_eval_comparison``): instead
    of running lanes itself, this call creates the lane jobs and enqueues as
    many as the concurrency cap allows, then returns immediately. Each lane
    runs as its own RQ job (see ``run_eval_lane_job``); the LAST lane job to
    finish computes the run's totals and finalises it, exactly as the code
    below does for the inline case.

    Scenario 5: an unexpected exception partway through must
    never leave the Run stuck on "Running" — the run is finalised as
    status="Error" with whatever partial results were collected, and the
    completion event STILL fires so the client script's realtime listener
    doesn't hang forever.
    """
    run = frappe.get_doc("AI Eval Run", run_name)

    if case_names is None:
        case_names = frappe.get_all(
            "AI Eval Case",
            filters={"suite": run.suite},
            pluck="name",
            order_by="creation asc",
        )

    if fan_out:
        fan_out_eval_suite(run, case_names)
        return

    try:
        passed = failed = skipped = 0
        total_cost = 0.0
        total_tokens = 0
        executions = passing_executions = 0
        # How many times each case runs. A replay re-scores one stored answer,
        # so repeating it would count the same execution k times and report a
        # consistency the run never demonstrated.
        pass_k = 1 if run.backend in ("replay", "deterministic") else max(1, cint(
            frappe.db.get_value("AI Eval Suite", run.suite, "pass_k")
        ))
        # a run may nominate an agent other than the suite's, so an
        # A/B comparison never has to rebind the suite. Resolved once here
        # rather than per case, so every case in a run is judged against the
        # same agent even if the suite is reassigned mid-run.
        agent_cfg = run.get("agent_configuration") or None
        # One ceiling for the whole run, drawn on by every lane. 0 means none.
        budget = {
            "cap": flt(run.get("spend_cap") or 0),
            "spent": 0.0,
            "not_run": 0,
            "lock": threading.Lock(),
        }
        rows = execute_lanes(
            case_names, run.name, run.backend, agent_cfg, pass_k, eval_concurrency(), budget
        )

        # Results are appended in the order the cases were asked for, never the
        # order they came back in. Lanes finish out of order — a one-word reply
        # lands long before a connector build — and a run's history has to read
        # the same either way, or comparing two runs becomes guesswork.
        for case_name in case_names:
            result_row = rows.get(case_name)
            if result_row is None:
                # A worker that died without recording anything would otherwise
                # drop the case silently and shrink the denominator.
                result_row = {
                    "eval_case": case_name,
                    "status": "Error",
                    "error_message": "This case produced no result. See the Error Log.",
                    "runs": 1, "passes": 0, "consistency_rate": 0,
                }
            # Snapshot what was evaluated, so later edits to the case don't
            # rewrite this run's history. Set centrally so every path (live,
            # replay, error) records it.
            snapshot = frappe.db.get_value(
                "AI Eval Case", case_name, ["input_user_prompt", "expected_output"], as_dict=True
            ) or {}
            result_row.setdefault("input_user_prompt", snapshot.get("input_user_prompt") or "")
            result_row.setdefault("expected_output", snapshot.get("expected_output") or "")
            run.append("results", result_row)
            if result_row["status"] == "Passed":
                passed += 1
            elif result_row["status"] == "Skipped":
                # Neither column: nothing was checked, so it is not evidence
                # either way. The caller decides whether a suite that checked
                # nothing is acceptable — see run_ai_evals.
                skipped += 1
            else:
                failed += 1
            if result_row["status"] != "Skipped":
                # Nothing ran, so it cannot be in the denominator. Counting it
                # would drag pass_rate down — and that rate is what the deploy
                # gate refuses on, so a suite would be blocked for having no
                # provider key rather than for behaving badly.
                executions += cint(result_row.get("runs") or 1)
                passing_executions += cint(result_row.get("passes") or 0)
            total_cost += flt(result_row.get("cost", 0))
            total_tokens += (result_row.get("tokens_used") or 0)

        if budget["not_run"]:
            run.stop_reason = (
                f"Stopped on budget: spent {budget['spent']:.4f} of a {budget['cap']:.4f} "
                f"ceiling; {budget['not_run']} case(s) not run."
            )

        run.total_cases = len(case_names)
        run.passed_cases = passed
        run.failed_cases = failed
        run.total_executions = executions
        run.pass_rate = (passing_executions / executions * 100) if executions else 0
        run.total_cost = total_cost
        run.total_tokens = total_tokens
        run.status = suite_run_status(run, failed)
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
    run.save(ignore_permissions=True)  # perms: the background finalise must not depend on the user's write rights
    # Background-job commit; skipped in tests so FrappeTestCase rollback
    # still cleans up fixture docs instead of leaking them into the DB.
    if not frappe.flags.in_test:
        frappe.db.commit()  # nosemgrep

    frappe.publish_realtime(
        "eval_run_completed",
        {"run_name": run.name, "status": run.status},
        user=run.owner,
    )
