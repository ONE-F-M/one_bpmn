# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Eval cases that exercise long-term memory."""

from __future__ import annotations

import json

import frappe


def _memory_case_spec(case) -> dict:
    """What a Memory case is asking for, read off the case.

    ``input_context`` carries the scope and its key, how many results to look
    at, and the agent output to distil when generation is being measured.
    ``expected_output`` holds the golden memories, one per line, because that is
    the field a person already edits when writing any other case.
    """
    spec = case.input_context
    if isinstance(spec, str):
        try:
            spec = json.loads(spec or "{}")
        except (ValueError, TypeError):
            spec = {}
    spec = dict(spec or {})
    golden = [line.strip() for line in (case.expected_output or "").splitlines() if line.strip()]
    spec.setdefault("golden_memories", golden)
    spec.setdefault("expected_recall", golden)
    # A generation case feeds the agent's own words to the distiller, so its
    # Input User Prompt is that output, not a question. Reading it as a query
    # would send the whole agent turn to memory search and measure nothing.
    if not spec.get("agent_output"):
        spec.setdefault("query", case.input_user_prompt or "")
    else:
        spec.setdefault("query", "")
    return spec


def _distil_for_eval(case, spec, scope, scope_key) -> list:
    """Run the distiller over the case's agent output and return what it kept.

    Nothing is written to the store: the case is asking what the distiller
    WOULD keep, and a suite that wrote memories every time it ran would change
    the thing it is measuring. This is the one part of a memory case that calls
    a model, so a generation case costs one distillation and a retrieval case
    still costs nothing.
    """
    from processa.ai_agent_memory.distill import distill_memories

    agent_cfg = frappe.db.get_value("AI Eval Suite", case.suite, "agent_configuration")
    cfg = frappe.get_cached_doc("AI Agent Configuration", agent_cfg) if agent_cfg else None
    model = spec.get("model") or (cfg and (cfg.memory_distill_model or cfg.ai_model)) or ""
    facts = distill_memories(
        spec["agent_output"],
        agent=str(scope_key),
        scope=scope,
        scope_key=scope_key,
        provider_name=spec.get("provider_name") or (cfg and cfg.ai_provider) or "",
        model=model,
    )
    return [f.get("content", "") for f in facts]


def _memory_case_user(eval_run: str = None) -> str:
    """Whose memories a case reads when it does not say.

    The run's owner, so a suite handed to a background worker measures what the
    person who started it would see, and the session user when there is no run
    to ask.
    """
    owner = frappe.db.get_value("AI Eval Run", eval_run, "owner") if eval_run else None
    return owner or frappe.session.user


def _scope_key_with_user(scope: str, scope_key, user: str):
    """Put a person on the scope key when the case names none.

    Recall always runs as somebody: memory_search returns that person's rows
    plus the shared ones. A case with no user reads the shared rows only, and
    on an agent whose memory scope includes User that is no rows at all, so a
    memory sitting right there scores 0 and the suite reports a retrieval
    failure that is really a missing filter.

    A case that means the shared rows says so with an explicit empty user; only
    a key that is silent gets the default.
    """
    if not isinstance(scope_key, dict):
        named = {"Agent": "agent_element", "Process": "process"}.get(scope)
        if not named:
            return scope_key
        scope_key = {named: scope_key}
    if scope_key.get("user") is None:
        scope_key = dict(scope_key, user=user)
    return scope_key


def execute_memory_case(case, eval_run: str = None) -> dict:
    """Measure the memory pipeline for one case.

    Reports generation precision/recall/F1 when the case says what should have
    been distilled, Recall@K and the retrieval latency when it asks a question,
    and passes only when everything it measured came out right and retrieval
    stayed inside its budget. Costs nothing: no agent is called, so tokens and
    cost stay at zero and a memory suite can run as often as anyone likes.
    """
    from processa.ai_agent_memory.evals import evaluate_memory_case

    spec = _memory_case_spec(case)
    scope = spec.get("scope") or "Agent"
    scope_key = spec.get("scope_key")
    if not scope_key:
        return {
            "eval_case": case.name,
            "status": "Error",
            "error_message": "A Memory case needs a scope_key in its Input Context, naming the memories to measure.",
        }

    produced = spec.get("produced_memories")
    if produced is None and spec.get("agent_output"):
        produced = _distil_for_eval(case, spec, scope, scope_key)

    report = evaluate_memory_case(
        scope=scope,
        scope_key=_scope_key_with_user(scope, scope_key, _memory_case_user(eval_run)),
        query=spec.get("query") or "",
        golden_memories=spec.get("golden_memories"),
        expected_recall=spec.get("expected_recall"),
        produced_memories=produced,
        k=int(spec.get("k") or 5),
    )
    return {
        "eval_case": case.name,
        "status": "Passed" if report["passed"] else "Failed",
        # The numbers are the result here, so they go where a reader already
        # looks for what happened.
        "actual_output": json.dumps(report, indent=2),
        "tokens_used": 0,
        "cost": 0.0,
    }
