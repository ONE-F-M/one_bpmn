# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Run records for the model calls an eval makes: their cost and the AI Agent Run each one is logged as."""

from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

from one_bpmn.agents.pricing import get_model_pricing


def cost_split(prompt_tokens: int, completion_tokens: int, model: str) -> tuple:
    """(input_cost, output_cost) for a call, from the model's rate card."""
    pricing = get_model_pricing(model) or {}
    return (
        (prompt_tokens / 1000.0) * flt(pricing.get("input_cost_per_1k", 0)),
        (completion_tokens / 1000.0) * flt(pricing.get("output_cost_per_1k", 0)),
    )


def record_eval_run(
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
            # an eval call is a single provider round-trip with no
            # human wait and no inter-step gap, so its wall time IS the agent
            # latency an AI Agent Run defines. Leaving these unset made every eval-origin
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
        }).insert(ignore_permissions=True)  # perms: a system log of the eval's own model call
    except Exception:
        frappe.log_error(
            title=f"AI Eval: run record failed ({bpmn_id})",
            message=frappe.get_traceback(),
        )
