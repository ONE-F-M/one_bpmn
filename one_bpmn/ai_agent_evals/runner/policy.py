# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Limits and planning for an eval run: timeouts, deadlines, concurrency, lanes and run status."""

from __future__ import annotations

from typing import List

import frappe
from frappe import _
from frappe.query_builder import DocType, Order
from frappe.utils import add_to_date, cint, flt, now_datetime

from one_bpmn.processa_engine.agent_runtime.executor import (
	DEFAULT_MAX_RETRIES,
	DEFAULT_TIMEOUT_SECONDS,
)


# live       calls the model.
# replay     re-scores each case's last stored answer — and still makes a judge
#            call for every llm_judge assertion, so it is not free and not
#            deterministic.
# deterministic
#            scores the answer recorded ON THE CASE and makes no model call at
#            all. That is what continuous integration can run before anyone has
#            decided whose provider key it may spend: it cannot tell you the
#            agent still behaves, only that the assertions and the evaluators
#            still do — which is exactly the regression a pull request
#            introduces.
EVAL_BACKENDS = ("live", "replay", "deterministic")


# RQ kills a job at its timeout, and a run saves its results once, at the end.
# A fixed 1800 s therefore lost every result of a suite that outgrew half an
# hour, which twenty-two live cases do.
# Five minutes per execution is generous for one case run once, and it is a
# bound, not a target.
MIN_JOB_TIMEOUT_SECONDS = 1800


SECONDS_PER_EXECUTION = 300


# One case execution's own worst case: the configured per-call timeout,
# multiplied by the call plus every retry the executor is allowed. A lane's
# RQ timeout is built from this, not from SECONDS_PER_EXECUTION's flat
# estimate, because it has to bound a REAL model call chain, not guess at one.
CASE_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS * (DEFAULT_MAX_RETRIES + 1)


# Slack added on top of the arithmetic sum of lane timeouts when computing a
# run's overall deadline for the sweep below. Bookkeeping (loading the case,
# writing the result row, enqueuing the next lane) is not free, and a sweep
# that fires the instant the last lane's timeout theoretically elapses would
# race a lane job that is still doing exactly that.
DEADLINE_MARGIN_SECONDS = 60


SPEND_CEILING_MESSAGE = "Not run - the run reached its spend ceiling."


# A hard ceiling regardless of configuration. Provider limits are per account,
# so an eval suite competes with live agent traffic; and spend that used to
# reveal itself slowly arrives all at once.
MAX_EVAL_CONCURRENCY = 8


def _case_timeout_seconds() -> int:
    """Seconds one case execution (all of its own retries) may take."""
    return CASE_TIMEOUT_SECONDS


def lane_timeout_seconds(lane: List[str], pass_k: int) -> int:
    """RQ timeout for the job that runs one lane.

    A lane runs its cases, and each case's pass_k repetitions, strictly one
    after another (that is the whole point of a lane), so the job's timeout is
    the sum of every case's worst case, repeated pass_k times.
    """
    case_count = max(1, len(lane))
    return max(MIN_JOB_TIMEOUT_SECONDS, _case_timeout_seconds() * case_count * max(1, pass_k))


def _suite_max_ai_timeout(suite_name: str) -> int:
    """The largest ``aiTimeout`` set on any AI Agent Task shape of the suite's
    map, in seconds, or 0 when the suite has no map or no shape sets one.

    Used only as an extra signal when sizing a run's deadline sweep \u2014 a map
    author who has already widened one shape's own timeout beyond the
    executor default is telling us this suite's cases legitimately run long.
    """
    process_model = frappe.db.get_value("AI Eval Suite", suite_name, "process_model")
    if not process_model:
        return 0
    serialized_spec = frappe.db.get_value("BPMN Process Model", process_model, "serialized_spec")
    if not serialized_spec:
        return 0
    try:
        spec = frappe.parse_json(serialized_spec) or {}
    except Exception:
        return 0
    extensions = (
        (spec.get("script_task_extensions") or {})
        if isinstance(spec, dict) else {}
    )
    best = 0
    for shape in (extensions or {}).values():
        if not isinstance(shape, dict):
            continue
        try:
            best = max(best, cint(shape.get("aiTimeout") or 0))
        except Exception:
            continue
    return best


def job_timeout(suite: str, backend: str, case_count: int) -> int:
    """Seconds RQ allows the run: the floor, or five minutes per execution,
    whichever is more. An execution is one case run once; pass_k repeats each
    live case that many times, and a replay repeats nothing."""
    pass_k = 1 if backend in ("replay", "deterministic") else max(
        1, cint(frappe.db.get_value("AI Eval Suite", suite, "pass_k"))
    )
    return max(MIN_JOB_TIMEOUT_SECONDS, SECONDS_PER_EXECUTION * max(1, case_count) * pass_k)


def resolve_agent_configuration_fallback(agent_cfg: str | None, process_model: str | None) -> str | None:
    """The suite's own agent, else the only AI Agent Configuration on its process model.

    Zero or several configurations on the process model give None.
    """
    if agent_cfg or not process_model:
        return agent_cfg or None
    matches = frappe.get_all(
        "AI Agent Configuration", filters={"process_model": process_model}, pluck="name", limit=2
    )
    return matches[0] if len(matches) == 1 else None


def find_reusable_running_run(suite_name: str, agent_cfg: str | None, backend: str) -> str | None:
    """The Running AI Eval Run for this suite, agent configuration and backend
    that is still inside its deadline, or None. A run past its deadline is not
    reused even before the sweep finalises it."""
    AIEvalRun = DocType("AI Eval Run")
    candidates = (
        frappe.qb.from_(AIEvalRun)
        .select(AIEvalRun.name, AIEvalRun.started_at)
        .where(AIEvalRun.suite == suite_name)
        .where(AIEvalRun.status == "Running")
        .where(AIEvalRun.backend == backend)
        .where(
            AIEvalRun.agent_configuration == agent_cfg
            if agent_cfg
            else (AIEvalRun.agent_configuration.isnull() | (AIEvalRun.agent_configuration == ""))
        )
        .orderby(AIEvalRun.started_at, order=Order.desc)
    ).run(as_dict=True)
    for candidate in candidates:
        if not candidate.started_at:
            continue
        run = frappe.get_doc("AI Eval Run", candidate.name)
        deadline = add_to_date(candidate.started_at, seconds=run_deadline_seconds(run))
        if now_datetime() < deadline:
            return candidate.name
    return None


def assert_agent_evaluatable(agent_cfg: str, eval_type: str, suite_map: str = "") -> None:
    """Block a live run whose agent can't be evaluated, with a clear message.
    Only "Agent" (process) evals need a map — a Google ADK agent
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


def eval_result_row_defaults(case_name: str, row: dict) -> dict:
    """Fill in the snapshot fields every result row needs, whichever path
    produced it (case, exception, or a never-ran case at finalise time)."""
    snapshot = frappe.db.get_value(
        "AI Eval Case", case_name, ["input_user_prompt", "expected_output"], as_dict=True
    ) or {}
    row = dict(row)
    row["eval_case"] = case_name
    row.setdefault("input_user_prompt", snapshot.get("input_user_prompt") or "")
    row.setdefault("expected_output", snapshot.get("expected_output") or "")
    return row


def run_case_names(run) -> list:
    """The ordered case list a run covers \u2014 its requested subset, or the
    whole suite when none was requested."""
    if run.get("requested_cases"):
        try:
            cases = frappe.parse_json(run.requested_cases)
        except Exception:
            cases = None
        if cases:
            return cases
    return frappe.get_all(
        "AI Eval Case", filters={"suite": run.suite}, pluck="name", order_by="creation asc"
    )


def run_deadline_seconds(run) -> float:
    """How long a fanned-out run may run before the sweep below finalises it:
    started_at + (sum of every lane's own timeout, divided across however many
    may run at once) + a fixed margin for the bookkeeping in between."""
    case_names = run_case_names(run)
    if not case_names:
        return DEADLINE_MARGIN_SECONDS
    pass_k = 1 if run.backend in ("replay", "deterministic") else max(1, cint(
        frappe.db.get_value("AI Eval Suite", run.suite, "pass_k")
    ))
    lanes = lanes_for(case_names)
    if not lanes:
        return DEADLINE_MARGIN_SECONDS
    concurrency = max(1, min(eval_concurrency(), len(lanes)))
    total_lane_seconds = sum(lane_timeout_seconds(lane, pass_k) for lane in lanes)
    return (total_lane_seconds / concurrency) + DEADLINE_MARGIN_SECONDS


def eval_concurrency() -> int:
    """How many lanes may be in flight. 1 — the default — is the old behaviour
    exactly: no pool, no threads, the same single-file loop."""
    try:
        configured = cint(frappe.db.get_single_value("Processa Settings", "eval_concurrency"))
    except Exception:
        return 1
    return max(1, min(configured or 1, MAX_EVAL_CONCURRENCY))


def lanes_for(case_names: List[str]) -> List[List[str]]:
    """Group cases into lanes that may run side by side.

    Two cases naming the same context document land in one lane, so they never
    overlap. Everything else gets a lane of its own. Lane order follows the
    order the cases were given, so a serial run and a parallel run schedule the
    same work in the same sequence.
    """
    contexts = {}
    if case_names:
        for row in frappe.get_all(
            "AI Eval Case",
            filters={"name": ["in", case_names]},
            fields=["name", "input_context"],
        ):
            docname = ""
            try:
                docname = (frappe.parse_json(row.input_context or "{}") or {}).get("context_docname") or ""
            except Exception:
                docname = ""
            contexts[row.name] = docname

    lanes: List[List[str]] = []
    by_document: dict = {}
    for case_name in case_names:
        document = contexts.get(case_name) or ""
        if not document:
            lanes.append([case_name])
            continue
        lane = by_document.get(document)
        if lane is None:
            lane = []
            by_document[document] = lane
            lanes.append(lane)
        lane.append(case_name)
    return lanes


def suite_run_status(run, failed: int) -> str:
    """Passed needs both bars the suite declares.

    Every case still has to pass — a single failing execution fails its case,
    which is the point of running it k times. On top of that, a suite that
    declares a minimum pass rate must meet it, and that rate is the number the
    deployment gate quotes. The two overlap today because the per-case bar is
    the stricter one; both are checked because the rate is what a reader is
    shown and what a gate refuses on, and a suite whose per-case rule is later
    relaxed must not silently open the gate.
    """
    if failed:
        return "Failed"
    minimum = flt(frappe.db.get_value("AI Eval Suite", run.suite, "min_pass_rate"))
    if minimum and flt(run.pass_rate) < minimum:
        return "Failed"
    return "Passed"
