# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Finishing an eval run and sweeping runs that never finished."""

from __future__ import annotations

import frappe
from frappe.query_builder import DocType
from frappe.utils import add_to_date, cint, flt, now_datetime

from one_bpmn.ai_agent_evals.runner.policy import (
	SPEND_CEILING_MESSAGE,
	eval_result_row_defaults,
	run_case_names,
	run_deadline_seconds,
	suite_run_status,
)


def maybe_finalize_eval_run(run_name: str, case_names: list) -> None:
    """Finalise the run once every case has a result \u2014 and not before."""
    result_count = frappe.db.count(
        "AI Eval Result", {"parent": run_name, "parenttype": "AI Eval Run"}
    )
    if result_count < len(case_names):
        return
    _force_finalize_if_running(run_name, case_names)


def _force_finalize_if_running(run_name: str, case_names: list) -> None:
    """Finalise *run_name* if, and only if, it is still Running \u2014 locked so
    two lane jobs (or a lane job and the deadline sweep) finishing at once
    finalise exactly once.

    The row lock is the guard: whichever caller's SELECT ... FOR UPDATE lands
    first sees status="Running" and finalises (which flips status away from
    Running before it commits, releasing the lock); the other blocks on the
    lock, then sees the new status and does nothing.
    """
    AIEvalRun = DocType("AI Eval Run")
    locked = (
        frappe.qb.from_(AIEvalRun)
        .select(AIEvalRun.name, AIEvalRun.status)
        .where(AIEvalRun.name == run_name)
        .for_update()
    ).run(as_dict=True)
    if not locked or locked[0].status != "Running":
        frappe.db.commit()  # nosemgrep - release the lock even when there is nothing to do
        return
    finalize_eval_run(run_name, case_names)


def finalize_eval_run(run_name: str, case_names: list) -> None:
    """Compute a fanned-out run's totals and status, and publish completion.

    Identical arithmetic to the inline path in ``execute_eval_suite``: results
    in case order, Skipped excluded from the denominator, everything else
    (Failed, Error, Timed Out) counted as failure. A case with no row at all
    \u2014 its lane job was killed, or the deadline swept it up first \u2014 is
    recorded here as Timed Out rather than silently shrinking the run.
    """
    run = frappe.get_doc("AI Eval Run", run_name)
    try:
        existing = {r.eval_case: r for r in (run.results or [])}
        passed = failed = skipped = 0
        total_cost = 0.0
        total_tokens = 0
        executions = passing_executions = 0

        for idx, case_name in enumerate(case_names, start=1):
            result_row = existing.get(case_name)
            if result_row is None:
                new_row = eval_result_row_defaults(case_name, {
                    "status": "Timed Out",
                    "error_message": (
                        "This case produced no result before the run was finalised "
                        "\u2014 its lane job was killed or the run's deadline passed."
                    ),
                    "runs": 1, "passes": 0, "consistency_rate": 0,
                })
                run.append("results", new_row)
                result_row = run.results[-1]

            status = result_row.status
            if status == "Passed":
                passed += 1
            elif status == "Skipped":
                skipped += 1
            else:
                # Failed, Error, Timed Out — all count as a failure.
                failed += 1
            if status != "Skipped":
                executions += cint(result_row.get("runs") or 1)
                passing_executions += cint(result_row.get("passes") or 0)
            total_cost += flt(result_row.get("cost") or 0)
            total_tokens += (result_row.get("tokens_used") or 0)

        not_run = sum(
            1 for r in run.results if r.status == "Skipped" and r.error_message == SPEND_CEILING_MESSAGE
        )
        if not_run:
            run.stop_reason = (
                f"Stopped on budget: spent {total_cost:.4f} of a {flt(run.spend_cap):.4f} "
                f"ceiling; {not_run} case(s) not run."
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
            title=f"AI Eval: fan-out finalise failed ({run_name})",
            message=frappe.get_traceback(),
        )
        run.status = "Error"
        run.total_cases = len(run.results or [])
        run.passed_cases = sum(1 for r in (run.results or []) if r.status == "Passed")
        run.failed_cases = run.total_cases - run.passed_cases

    run.ended_at = now_datetime()
    run.save(ignore_permissions=True)  # perms: the sweep finalises stale runs as a system job
    frappe.db.commit()  # nosemgrep

    # Realtime goes to whoever started the run, never "all".
    frappe.publish_realtime(
        "eval_run_completed",
        {"run_name": run.name, "status": run.status},
        user=run.owner,
    )


def sweep_stale_eval_runs() -> None:
    """Scheduled every five minutes: finalise any Running AI Eval Run whose
    deadline has passed, recording whatever case never produced a result as
    Timed Out.

    This is the backstop for a lane job that was killed without ever getting
    to enqueue its own successor or check whether it was the last lane home
    \u2014 without it, that run would sit on "Running" forever.
    """
    running = frappe.get_all(
        "AI Eval Run",
        filters={"status": "Running"},
        fields=["name", "suite", "backend", "started_at", "requested_cases"],
    )
    now = now_datetime()
    for run in running:
        try:
            if not run.started_at:
                continue
            deadline = add_to_date(run.started_at, seconds=run_deadline_seconds(run))
            if now < deadline:
                continue
            case_names = run_case_names(run)
            _force_finalize_if_running(run.name, case_names)
        except Exception:
            frappe.log_error(
                title=f"AI Eval: deadline sweep failed ({run.name})",
                message=frappe.get_traceback(),
            )
