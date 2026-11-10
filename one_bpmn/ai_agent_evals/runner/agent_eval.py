# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Evaluating an agent for one case: map, chat agent and direct model paths."""

from __future__ import annotations

import json
from typing import List

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, now_datetime

from one_bpmn.processa_engine.agent_runtime.executor import (
	ErrorCode,
	ExecutorConfig,
	ExecutorContext,
	get_executor,
)
from one_bpmn.agents.pricing import get_model_pricing
# Importing the backend modules registers them in the executor registry.
from one_bpmn.processa_engine.agent_runtime.direct_api import (  # noqa: F401
	DirectApiExecutor,
	strip_code_fences,
)
from one_bpmn.processa_engine.agent_runtime.antigravity import AntigravityExecutor  # noqa: F401

from one_bpmn.ai_agent_evals.runner.assertions import EVAL_RUN_JUDGE, completion_tokens_of, prompt_tokens_of
from one_bpmn.ai_agent_evals.runner.records import record_eval_run


# bpmn_id markers for the eval LLM calls recorded as AI Agent Runs (origin="eval").
EVAL_RUN_DIRECT = "direct-eval"


# input_context keys a chat case uses to seed its conversation's earlier turns.
SEED_MESSAGES_KEY = "conversation_messages"


SEED_STATE_KEY = "session_state"


SEED_MESSAGE_TYPES = ("User", "Bot", "Tool")


# Reply intents whose bpmn_xml is appended to the output the assertions read.
DIAGRAM_INTENTS = ("BPMN_GENERATED", "BPMN_MODIFIED")


def eval_origin_flag(case, eval_run: str = None) -> dict:
    """The ``frappe.flags.eval_origin`` payload for one case's execution.

    Both creators of eval-origin AI Agent Runs read it — ``observability.create_ai_run``
    for the agent's own runs, and ``record_eval_run`` for the direct call and each
    judge call — so the back-links cannot drift between them.
    """
    return {"eval_case": case.name, "eval_run": eval_run or ""}


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


def _instance_failure(instance_name: str) -> str:
    """What the engine logged when this instance errored.

    The instance keeps no error field — the traceback goes to an Error Log
    titled "BPMN runtime failure [<ref>] — <instance>" — so the last line of
    that log is the only thing that says what actually broke.
    """
    log = frappe.get_all(
        "Error Log",
        filters={"method": ["like", f"BPMN runtime failure%{instance_name}"]},
        fields=["error"],
        order_by="creation desc",
        limit=1,
    )
    if not log:
        return "No BPMN runtime failure was logged for it."
    lines = [line for line in (log[0].error or "").strip().splitlines() if line.strip()]
    return f"It failed with: {lines[-1].strip()}" if lines else "Its Error Log is empty."


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


def _worker_answer(doctype: str, docname: str) -> str:
    """What a delegated worker handed back to its caller, or "" if it is not one.

    A tool-using worker's last model message is narration — "the test passed, now
    let me finalize" — while the answer itself is assembled by the map's final
    script and written onto the worker's own A2A Task. Judging the narration
    scores the commentary and misses the work: the Connector Agent reported a
    written, disabled connector on the task while its last message talked about
    the test it had just run.
    """
    if doctype != "A2A Task" or not docname:
        return ""
    row = frappe.db.get_value("A2A Task", docname, ["result", "status_message"], as_dict=True) or {}
    return (row.get("result") or "").strip() or (row.get("status_message") or "").strip()


def _parked_answer(run: dict) -> str:
    """What a run that stopped to ask a person had said, plus the question it asked.

    The executor checkpoints the call it parks on instead of finishing the
    turn, so a run that asked the story owner has no final_output and, once the
    eval cancels the instance, never will. The checkpoint is the only witness:
    the last thing the model said and the tool it reached for.
    """
    if run.get("status") != "Suspended":
        return ""
    suspension = _suspension_of(run.get("checkpoint"))
    said = ""
    for message in reversed(suspension.get("transcript") or []):
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
        if message.get("role") == "assistant" and content:
            said = content
            break
    pending = suspension.get("pending_call") or {}
    if not pending.get("name"):
        return said
    asked = f"Stopped to ask a person through {pending['name']}: {json.dumps(pending.get('arguments') or {})}"
    return "\n\n".join(part for part in (said, asked) if part)


def _suspension_of(checkpoint) -> dict:
    try:
        return json.loads(checkpoint or "{}").get("suspension") or {}
    except (ValueError, AttributeError):
        return {}


def parked_calls(runs: List[str]) -> List[dict]:
    """The call each Suspended run parked on, read off its checkpoint.

    A model that asks a person has made that call, but the executor records no
    Tool Call row for it, so a trajectory case saw "Called: nothing" and failed
    a run that had done exactly what it should.
    """
    parked = []
    for run in frappe.get_all(
        "AI Agent Run",
        filters={"name": ["in", runs], "status": "Suspended"},
        fields=["checkpoint"],
        order_by="creation asc",
    ):
        pending = _suspension_of(run.checkpoint).get("pending_call") or {}
        if pending.get("name"):
            parked.append({"tool": pending["name"], "args": pending.get("arguments") or {}, "status": "Parked"})
    return parked


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
    instance.insert(ignore_permissions=True)  # perms: a system-started eval run for a caller already authorised to run the suite

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

    # A script the map ran can call frappe.db.rollback() and take this
    # transaction with it: the instance inserted above is gone, the run with it,
    # and the lookup below would blame the map's routing.
    if not frappe.db.exists("BPMN Process Instance", instance.name):
        raise ValueError(
            f"Process map '{model_name}' rolled the transaction back while running on "
            f"{doctype} '{docname}': the instance this eval inserted no longer exists. A script "
            f"on the map calls frappe.db.rollback(); it should roll back to a savepoint of its own."
        )

    # The engine handles its own failures: it logs the traceback, marks the
    # instance Errored and returns, so an exception escaping start() is NOT what
    # a failed run looks like. Asked before the run lookup because a run that
    # never happened is the symptom, and the missing run below would otherwise
    # be blamed on the map's routing.
    if frappe.db.get_value("BPMN Process Instance", instance.name, "status") == "Errored":
        raise ValueError(
            f"Process map '{model_name}' errored on {doctype} '{docname}' "
            f"(instance {instance.name}). {_instance_failure(instance.name)}"
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
        fields=["final_output", "status", "checkpoint", "total_prompt_tokens",
                "total_completion_tokens", "total_tokens", "estimated_cost"],
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
    output = (
        _worker_answer(doctype, docname)
        or runs[-1].get("final_output")
        or _parked_answer(runs[-1])
    )
    usage = {
        "prompt_tokens": sum((r.get("total_prompt_tokens") or 0) for r in runs),
        "completion_tokens": sum((r.get("total_completion_tokens") or 0) for r in runs),
        "tokens": sum((r.get("total_tokens") or 0) for r in runs),
        "cost": sum(flt(r.get("estimated_cost")) for r in runs),
    }
    return output, usage


def run_agent_eval(cfg, case, eval_run: str = None) -> tuple:
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
    frappe.flags.eval_origin = eval_origin_flag(case, eval_run)
    frappe.flags.bpmn_disable_ai_parking = True
    try:
        if _needs_map_eval(cfg):
            return _run_map_eval(cfg, case)
        return _run_chat_agent_eval(cfg, case, eval_run)
    finally:
        frappe.flags.eval_origin, frappe.flags.bpmn_disable_ai_parking = prev


def _run_chat_agent_eval(cfg, case, eval_run: str | None = None) -> tuple:
    """The chat-shaped Agent eval: hand the turn to ``invoke_agent`` on a fresh conversation.
    ``input_context`` may seed earlier turns through ``conversation_messages`` and
    ``session_state``; usage comes from the runs tagged with this case and eval run."""
    from one_bpmn.ai_agent_conversations import session_state
    from one_bpmn.ai_agent_conversations.chat_persistence import close_conversation, create_agent_conversation
    from one_bpmn.api.a2a import invoke_agent

    if not cfg.agent_id:
        raise ValueError(f"Agent configuration '{cfg.name}' has no agent_id.")

    context = {}
    if case.input_context:
        try:
            context = frappe.parse_json(case.input_context) or {}
        except Exception:
            context = {}
    seed_messages = context.pop(SEED_MESSAGES_KEY, None) or []
    seed_state = context.pop(SEED_STATE_KEY, None) or {}

    # No commit: the eval job commits when its case ends, and a test's rollback must reach this row.
    conversation = create_agent_conversation(
        cfg.agent_id, title=(case.title or _("Eval case"))[:140], user=frappe.session.user, commit=False
    )
    frappe.db.set_value("Chat Conversation", conversation, "is_eval", 1, update_modified=False)

    started = now_datetime()
    try:
        _seed_conversation(conversation, seed_messages, seed_state)
        reply = invoke_agent(
            cfg.agent_id, case.input_user_prompt or "", conversation=conversation, context=context
        )
    finally:
        close_conversation(conversation)
        session_state.clear_state(conversation)

    reply = reply or {}
    output = reply.get("response") or ""
    # A diagram turn's lanes and shapes live only in its XML, so assertions read it after the reply.
    if (reply.get("intent") or "").upper() in DIAGRAM_INTENTS and reply.get("bpmn_xml"):
        output = output + "\n\n" + reply["bpmn_xml"]
    # A DocType turn's fields live only in its definition, so assertions read it after the reply.
    doctype_ir = reply.get("doctype_ir") or _saved_doctype_ir(conversation)
    if doctype_ir:
        output = output + "\n\n" + json.dumps(doctype_ir, indent=1, default=str)

    # creation >= started keeps each repeated attempt under one eval_run to its own runs.
    filters = {
        "eval_case": case.name,
        "creation": [">=", started],
        # _execute_case adds judge spend separately.
        "bpmn_id": ["!=", EVAL_RUN_JUDGE],
    }
    if eval_run:
        filters["eval_run"] = eval_run
    runs = frappe.get_all(
        "AI Agent Run",
        filters=filters,
        fields=["total_prompt_tokens", "total_completion_tokens", "total_tokens", "estimated_cost"],
    )
    if not runs:
        raise ValueError(
            _(
                "Agent '{0}' ran but produced no AI Agent Run for case '{1}'. "
                "Check that the agent's map reaches its AI Agent Task for this conversation."
            ).format(cfg.name, case.name)
        )
    usage = {
        "prompt_tokens": sum((r.get("total_prompt_tokens") or 0) for r in runs),
        "completion_tokens": sum((r.get("total_completion_tokens") or 0) for r in runs),
        "tokens": sum((r.get("total_tokens") or 0) for r in runs),
        "cost": sum(flt(r.get("estimated_cost")) for r in runs),
    }
    return output, usage


def _saved_doctype_ir(conversation: str):
    """The DocType definition on the conversation's latest reply, as the schema card shows it."""
    metadata = frappe.db.get_value(
        "Chat Message", {"conversation": conversation, "message_type": "Bot"}, "metadata",
        order_by="creation desc",
    )
    agent_result = (frappe.parse_json(metadata) or {}).get("agent_result") if metadata else None
    return agent_result.get("doctype_ir") if isinstance(agent_result, dict) else None


def _seed_conversation(conversation: str, messages: list, state: dict) -> None:
    """Write earlier turns and session state into an eval conversation, oldest first."""
    from one_bpmn.ai_agent_conversations import session_state

    start = add_to_date(now_datetime(), seconds=-len(messages) - 1)
    for index, message in enumerate(messages):
        message_type = message.get("message_type")
        if message_type not in SEED_MESSAGE_TYPES:
            raise ValueError(
                f"Seeded message {index + 1} has message_type {message_type!r}; "
                f"use one of {', '.join(SEED_MESSAGE_TYPES)}."
            )
        metadata = message.get("metadata")
        doc = frappe.get_doc(
            {
                "doctype": "Chat Message",
                "conversation": conversation,
                "message_type": message_type,
                "text": message.get("text") or "",
                "metadata": json.dumps(metadata) if isinstance(metadata, (dict, list)) else metadata,
                "sender": frappe.session.user if message_type == "User" else "Administrator",
            }
        )
        doc.creation = doc.modified = add_to_date(start, seconds=index)
        doc.owner = doc.modified_by = frappe.session.user
        # db_insert: seeded history is a fixture, not a message sent through the chat's guards.
        doc.db_insert()
    if state:
        session_state.set_state(conversation, state, commit=False)


def run_direct_eval(cfg, case) -> tuple:
    """Direct (simple) eval: a plain LLM call with the agent's provider/model/
    system prompt. Records a standalone eval-origin AI Agent Run so the call
    shows in Insights alongside process (agent) evals."""
    provider = cfg.ai_provider or ""
    # the MODEL is the agent's own catalog pick and the credentials
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
        "AI Model", {"provider": provider, "enable_model": 1}, "name"
    ) or ""

    started = now_datetime()
    config = ExecutorConfig(
        backend="direct_api",
        provider_name=provider,
        model=model,
        system_prompt=cfg.system_prompt or "",
        user_prompt=case.input_user_prompt or "",
        # Pinned to 0.7 on purpose, not DEFAULT_TEMPERATURE.
        temperature=0.7,
    )
    result = get_executor("direct_api")().run(config, ExecutorContext())
    if result.error_code != ErrorCode.SUCCESS:
        raise RuntimeError(result.error_message or result.error_code.value)

    prompt_tokens = prompt_tokens_of(result)
    completion_tokens = completion_tokens_of(result)
    pricing = get_model_pricing(model)
    if not pricing:
        # Tokens are still counted; without a rate on the model the cost
        # would silently read $0.00, so leave a trace explaining why.
        frappe.log_error(
            title="AI Eval: no pricing for direct-eval model",
            message=f"No rate card on AI Model '{model}' "
            f"(provider {provider}); cost recorded as 0 for case {case.name}.",
        )
        pricing = {}
    input_cost = (prompt_tokens / 1000.0) * flt(pricing.get("input_cost_per_1k", 0))
    output_cost = (completion_tokens / 1000.0) * flt(pricing.get("output_cost_per_1k", 0))

    record_eval_run(
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
