# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Lane workers: how a suite's cases are fanned out, run in parallel and written back."""

from __future__ import annotations

import queue
import threading
from typing import List

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt

from processa.ai_agent_evals.runner.cases import execute_case_k_times
from processa.ai_agent_evals.runner.policy import (
	SPEND_CEILING_MESSAGE,
	eval_concurrency,
	eval_result_row_defaults,
	lane_timeout_seconds,
	lanes_for,
)
from processa.ai_agent_evals.runner.sweep import finalize_eval_run, maybe_finalize_eval_run


def _write_eval_result_row(run_name: str, case_name: str, row: dict, idx: int) -> None:
    """Insert one case's result directly as a child row of the run, durably.

    Written and committed by the caller immediately after \u2014 this function
    only builds and inserts the row; it does not commit, so a caller writing
    several rows in one case's retry chain still controls its own commit
    point.
    """
    payload = eval_result_row_defaults(case_name, row)
    payload.update({
        "doctype": "AI Eval Result",
        "parent": run_name,
        "parenttype": "AI Eval Run",
        "parentfield": "results",
        "idx": idx,
    })
    frappe.get_doc(payload).insert(ignore_permissions=True)  # perms: the lane job writes the result row on the caller's behalf


def _is_job_timeout_exception(exc: BaseException) -> bool:
    """True for RQ's own timeout kill, which must never be swallowed as an
    ordinary case failure \u2014 it has to keep propagating so the job actually
    dies and leaves its in-flight case for the deadline sweep to record."""
    try:
        from rq.timeouts import JobTimeoutException
    except Exception:
        return False
    return isinstance(exc, JobTimeoutException)


def fan_out_eval_suite(run, case_names: list) -> None:
    """Kick off a run's lanes as background jobs and return immediately.

    Called by ``execute_eval_suite(fan_out=True)``. Each lane job checks the
    run's spend ceiling against committed results before every case.
    """
    if not case_names:
        finalize_eval_run(run.name, case_names)
        return

    pass_k = 1 if run.backend in ("replay", "deterministic") else max(1, cint(
        frappe.db.get_value("AI Eval Suite", run.suite, "pass_k")
    ))
    agent_cfg = run.get("agent_configuration") or None
    lanes = lanes_for(case_names)
    concurrency = max(1, min(eval_concurrency(), len(lanes)))

    # The lane jobs read through their own connections; anything this
    # transaction has not committed does not exist as far as they are
    # concerned. Skipped under test, where FrappeTestCase's rollback is what
    # cleans up the fixtures afterwards.
    if not frappe.flags.in_test:
        frappe.db.commit()  # nosemgrep

    for lane_index in range(concurrency):
        frappe.enqueue(
            "processa.ai_agent_evals.runner.lanes.run_eval_lane_job",
            queue="bpmn_ai_agent",
            run_name=run.name,
            case_names=case_names,
            backend=run.backend,
            agent_cfg=agent_cfg,
            pass_k=pass_k,
            lane_index=lane_index,
            concurrency=concurrency,
            timeout=lane_timeout_seconds(lanes[lane_index], pass_k),
        )


def run_eval_lane_job(run_name: str, case_names: list, backend: str, agent_cfg: str | None,
                        pass_k: int, lane_index: int, concurrency: int) -> None:
    """One lane, as its own RQ job.

    Every case this lane runs gets its own AI Eval Result row, written and
    committed the instant that case finishes \u2014 so a job killed on its
    timeout loses only the case it was running, never the ones before it.
    A ``JobTimeoutException`` is deliberately let through: catching it would
    turn RQ's own kill signal into an ordinary "this case errored" row, which
    is not what happened and would stop the job from actually dying on
    schedule.
    """
    lanes = lanes_for(case_names)
    if lane_index >= len(lanes):
        return
    lane = lanes[lane_index]
    order_index = {name: i + 1 for i, name in enumerate(case_names)}
    spend_cap, owner = frappe.db.get_value("AI Eval Run", run_name, ["spend_cap", "owner"])
    spend_cap = flt(spend_cap)
    AIEvalResult = DocType("AI Eval Result")

    for case_name in lane:
        # Committed rows are the only spend every lane job can see.
        spent = flt((
            frappe.qb.from_(AIEvalResult)
            .select(Sum(AIEvalResult.cost))
            .where(AIEvalResult.parent == run_name)
            .where(AIEvalResult.parenttype == "AI Eval Run")
        ).run()[0][0]) if spend_cap else 0.0
        if spend_cap and spent >= spend_cap:
            row = {
                "eval_case": case_name,
                "status": "Skipped",
                "error_message": SPEND_CEILING_MESSAGE,
                "runs": 0, "passes": 0, "consistency_rate": 0,
            }
        else:
            try:
                case = frappe.get_doc("AI Eval Case", case_name)
                row = execute_case_k_times(run_name, backend, case, agent_cfg, pass_k)
            except Exception as exc:
                if _is_job_timeout_exception(exc):
                    raise
                frappe.log_error(
                    title=f"AI Eval: case execution failed ({case_name})",
                    message=frappe.get_traceback(),
                )
                row = {
                    "eval_case": case_name,
                    "status": "Error",
                    "error_message": "This case could not be executed. See the Error Log.",
                    "runs": 1, "passes": 0, "consistency_rate": 0,
                }
        _write_eval_result_row(run_name, case_name, row, order_index[case_name])
        # Unconditional: this write has to survive even when the very next
        # line never runs because the job is killed. Unlike the inline path,
        # a lane job's whole reason to exist is that its results outlive it.
        frappe.db.commit()  # nosemgrep
        frappe.publish_realtime(
            "eval_case_completed",
            {
                "run_name": run_name,
                "eval_case": case_name,
                "status": row["status"],
                "done": frappe.db.count("AI Eval Result", {"parent": run_name, "parenttype": "AI Eval Run"}),
                "total": len(case_names),
            },
            user=owner,
        )

    next_index = lane_index + concurrency
    if next_index < len(lanes):
        frappe.enqueue(
            "processa.ai_agent_evals.runner.lanes.run_eval_lane_job",
            queue="bpmn_ai_agent",
            run_name=run_name,
            case_names=case_names,
            backend=backend,
            agent_cfg=agent_cfg,
            pass_k=pass_k,
            lane_index=next_index,
            concurrency=concurrency,
            timeout=lane_timeout_seconds(lanes[next_index], pass_k),
        )

    maybe_finalize_eval_run(run_name, case_names)


def _run_lane(lane: List[str], run_name: str, backend: str, agent_cfg: str | None, pass_k: int,
              budget: dict | None = None) -> dict:
    """Execute one lane's cases in order, returning {case: result row}.

    A case that blows up is recorded as an Error and the lane carries on: one
    bad case must not cost the others their turn, which is the same rule the
    serial runner has always followed.

    *budget* is the run's spend ceiling, shared with every other lane. It is
    checked before each case and never mid-case: cutting off an answer already
    being paid for wastes it. With lanes running side by side, up to one case
    per lane may already be in flight when the ceiling is reached, so the run
    can land a little over it — the alternative is refusing to start anything
    until every lane reports, which is slower for no real protection.
    """
    rows = {}
    for case_name in lane:
        if _budget_spent(budget):
            rows[case_name] = {
                "eval_case": case_name,
                "status": "Skipped",
                "error_message": "Not run \u2014 the run reached its spend ceiling.",
                "runs": 0, "passes": 0, "consistency_rate": 0,
            }
            with budget["lock"]:
                budget["not_run"] += 1
            continue
        try:
            case = frappe.get_doc("AI Eval Case", case_name)
            rows[case_name] = execute_case_k_times(run_name, backend, case, agent_cfg, pass_k)
        except Exception:
            frappe.log_error(
                title=f"AI Eval: case execution failed ({case_name})",
                message=frappe.get_traceback(),
            )
            rows[case_name] = {
                "eval_case": case_name,
                "status": "Error",
                "error_message": "This case could not be executed. See the Error Log.",
                "runs": 1,
                "passes": 0,
                "consistency_rate": 0,
            }
        _budget_draw(budget, rows[case_name].get("cost"))
    return rows


def _budget_spent(budget: dict | None) -> bool:
    """True once the run has spent what it was allowed."""
    if not budget or not budget.get("cap"):
        return False
    with budget["lock"]:
        return budget["spent"] >= budget["cap"]


def _budget_draw(budget: dict | None, cost) -> None:
    """Add what a case cost to the run's running total."""
    if not budget or not budget.get("cap"):
        return
    with budget["lock"]:
        budget["spent"] += flt(cost)


def _lane_worker(site: str, lanes: "queue.Queue", results: dict, lock: "threading.Lock",
                 run_name: str, backend: str, agent_cfg: str | None, pass_k: int,
                 budget: dict | None = None) -> None:
    """One worker: its own Frappe context, then lanes until the queue is empty.

    The context is set up ONCE per worker rather than per lane — a connect is
    far more expensive than a case — and it has to exist at all, because a
    thread inherits none of it. Without it there is no database connection and,
    worse, no eval-origin stamp on the runs the case produces, which is what
    later attributes a tool-call trace to its case. That failure is silent: the
    suite passes and the trace assertions quietly find nothing to look at.
    """
    frappe.init(site=site)
    frappe.connect()
    try:
        while True:
            try:
                lane = lanes.get_nowait()
            except queue.Empty:
                return
            try:
                rows = _run_lane(lane, run_name, backend, agent_cfg, pass_k, budget)
                # Each worker owns its own transaction, so its writes are its own
                # to commit. Without this the case's AI Agent Runs — and every
                # judge call recorded against them — roll back when the thread
                # ends, while the row it returns still says it all happened.
                frappe.db.commit()  # nosemgrep
                with lock:
                    results.update(rows)
            finally:
                lanes.task_done()
    finally:
        frappe.destroy()


def execute_lanes(case_names: List[str], run_name: str, backend: str,
                   agent_cfg: str | None, pass_k: int, concurrency: int,
                   budget: dict | None = None) -> dict:
    """Run every case, side by side up to ``concurrency`` lanes, and return
    {case: result row}.

    At concurrency 1 this is the plain loop it has always been: no queue, no
    threads, no per-worker connect. That is not an optimisation so much as a
    guarantee — the default configuration runs the code path that has been in
    production all along.
    """
    lanes = lanes_for(case_names)
    if concurrency <= 1 or len(lanes) <= 1:
        rows = {}
        for lane in lanes:
            rows.update(_run_lane(lane, run_name, backend, agent_cfg, pass_k, budget))
        return rows

    # Each worker reads through its OWN database connection, so it cannot see
    # writes this transaction has not committed — every case would come back
    # "not found". A background job has nothing pending worth protecting here,
    # and the runner commits at the end anyway; skipped under test so the
    # framework's rollback still cleans up fixtures.
    if not frappe.flags.in_test:
        frappe.db.commit()  # nosemgrep

    pending: "queue.Queue" = queue.Queue()
    for lane in lanes:
        pending.put(lane)

    results: dict = {}
    lock = threading.Lock()
    workers = [
        threading.Thread(
            target=_lane_worker,
            args=(frappe.local.site, pending, results, lock, run_name, backend, agent_cfg,
                  pass_k, budget),
            name=f"eval-{run_name}-{index}",
            daemon=True,
        )
        for index in range(min(concurrency, len(lanes)))
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return results
