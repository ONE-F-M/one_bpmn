# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Shared factories and mocking helpers for the AI eval test suite.

This module is imported by test_eval_runner.py, test_eval_judge.py and
test_eval_gating.py. It is deliberately NOT named test_* so the framework
does not collect it as a test module.

The factories create AI Eval Suite / Case / Run documents with
``ignore_mandatory`` and ``ignore_links`` set so tests do not need real
AI Provider or BPMN Process Model fixtures. ``patch_executor`` swaps the
runner's executor lookup for a fake so no real LLM calls are made.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Union
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage


# ---------------------------------------------------------------------------
# Document factories
# ---------------------------------------------------------------------------

def make_agent_configuration(**kwargs) -> "frappe.model.document.Document":
    """Create and insert a minimal AI Agent Configuration for a suite to test.

    WI-001751 made the agent the subject of an eval: AI Eval Suite.agent_configuration
    is mandatory, and the runner reads the agent for the provider, model and system
    prompt a case runs against. A suite without one cannot execute at all — every
    case comes back Error("The suite has no agent configuration to test.").

    agent_id and chat_mode_label are hashed per call because
    validate_unique_chat_mode_label rejects two enabled Chat agents sharing a
    label, which would otherwise make these fixtures collide with each other.
    """
    suffix = frappe.generate_hash(length=8)
    defaults = {
        "doctype": "AI Agent Configuration",
        "agent_name": f"_Test Eval Agent {suffix}",
        "agent_id": f"_test_eval_agent_{suffix}",
        "agent_framework": "Direct API",
        "agent_type": "Chat",
        "chat_mode_label": f"_Test Eval Agent {suffix}",
        "enabled": 1,
        "lifecycle_status": "Live",
        "system_prompt": "You are a test agent.",
    }
    defaults.update(kwargs)
    doc = frappe.get_doc(defaults)
    doc.flags.ignore_mandatory = True
    doc.flags.ignore_links = True
    return doc.insert(ignore_permissions=True)


def make_eval_suite(**kwargs) -> "frappe.model.document.Document":
    """Create and insert an AI Eval Suite with sensible test defaults.

    An agent configuration is created and linked unless the caller supplies
    ``agent_configuration`` — pass ``agent_configuration=None`` explicitly to
    build the agent-less suite the runner is supposed to refuse.
    """
    defaults = {
        "doctype": "AI Eval Suite",
        "title": "_Test Eval Suite " + frappe.generate_hash(length=8),
        "process_model": "_Test BPMN Model",
        "eval_type": "Direct",
        "gate_deployment": 0,
    }
    defaults.update(kwargs)
    if "agent_configuration" not in kwargs:
        defaults["agent_configuration"] = make_agent_configuration().name
    doc = frappe.get_doc(defaults)
    doc.flags.ignore_mandatory = True
    doc.flags.ignore_links = True
    return doc.insert(ignore_permissions=True)


def make_eval_case(assertions=None, **kwargs) -> "frappe.model.document.Document":
    """
    Create and insert an AI Eval Case with sensible test defaults.

    *assertions* is an optional list of dicts appended to the case's
    ``assertions`` child table, e.g. ``[{"assertion_type": "contains",
    "value": "approved"}]``.
    """
    # WI-001751 removed provider / model / backend from AI Eval Case — those now
    # come from the suite's agent — so a case carries only the test itself.
    defaults = {
        "doctype": "AI Eval Case",
        "title": "_Test Eval Case " + frappe.generate_hash(length=8),
        "input_user_prompt": "Say the magic word.",
    }
    defaults.update(kwargs)
    doc = frappe.get_doc(defaults)
    for assertion in (assertions or []):
        doc.append("assertions", assertion)
    doc.flags.ignore_mandatory = True
    doc.flags.ignore_links = True
    return doc.insert(ignore_permissions=True)


def make_eval_run(suite: str, **kwargs) -> "frappe.model.document.Document":
    """Create and insert an AI Eval Run linked to *suite*."""
    defaults = {
        "doctype": "AI Eval Run",
        "suite": suite,
        "status": "Running",
        "backend": "live",
        "started_at": now_datetime(),
    }
    defaults.update(kwargs)
    doc = frappe.get_doc(defaults)
    doc.flags.ignore_links = True
    return doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Executor result builders
# ---------------------------------------------------------------------------

def success_result(output: Any, tokens: int = 0) -> ExecutorResult:
    """An ExecutorResult with error_code=SUCCESS and the given *output*."""
    return ExecutorResult(
        output=output,
        token_usage=TokenUsage(total_tokens=tokens),
        error_code=ErrorCode.SUCCESS,
    )


def error_result(
    message: str = "executor failed",
    code: ErrorCode = ErrorCode.FAILED_MODEL_CALL,
) -> ExecutorResult:
    """An ExecutorResult representing a non-success executor outcome."""
    return ExecutorResult(output=None, error_code=code, error_message=message)


# ---------------------------------------------------------------------------
# Executor mocking
# ---------------------------------------------------------------------------

Handler = Union[ExecutorResult, Callable[[Any, Any], ExecutorResult]]


@contextmanager
def patch_executor(handler: Handler):
    """
    Patch the eval runner's ``get_executor`` so no real LLM call is made.

    *handler* is either an ExecutorResult returned for every case, or a
    callable ``handler(config, context) -> ExecutorResult``. A callable may
    raise to simulate an executor crash; the runner's per-case try/except
    must capture it as an Error result.

    Also neutralises ``frappe.db.commit`` (so the test's auto-rollback still
    works), ``frappe.publish_realtime`` and ``frappe.log_error`` for the
    duration of the block.
    """
    if not callable(handler):
        result = handler
        def handler(config, context):  # noqa: E731 - intentional shadow
            return result

    fake_cls = type(
        "PatchedExecutor",
        (),
        {"run": lambda self, config, context: handler(config, context)},
    )

    with patch("one_bpmn.agents.eval_runner.get_executor", return_value=fake_cls), \
            patch("frappe.publish_realtime"), \
            patch("frappe.log_error"), \
            patch.object(frappe.db, "commit"):
        yield
