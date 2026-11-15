# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Comparing an eval suite across agent configurations."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from processa.ai_agent_evals.runner.policy import assert_agent_evaluatable, job_timeout


@frappe.whitelist(methods=["POST"])
def run_eval_comparison(
    suite_name: str,
    agent_b: str,
    agent_a: str | None = None,
    case_names: list[str] | str | None = None,
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
            assert_agent_evaluatable(agent, suite.eval_type, suite.process_model)

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
        run.insert(ignore_permissions=True)  # perms: system-written run record; the caller was authorised above
        runs.append(run.name)

    for run_name in runs:
        frappe.enqueue(
            "processa.ai_agent_evals.runner.suite.execute_eval_suite",
            queue="bpmn_ai_agent",
            run_name=run_name,
            case_names=case_names,
            fan_out=True,
            job_id=f"eval-run::{run_name}",
            deduplicate=True,
            timeout=job_timeout(suite_name, "live", len(case_names)),
        )

    return {
        "comparison_group": group,
        "run_a": runs[0],
        "run_b": runs[1],
        "agent_a": agent_a,
        "agent_b": agent_b,
        "total_cases": len(case_names),
    }
