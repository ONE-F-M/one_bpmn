# Copyright (c) 2026, one-fm and contributors
"""
ProsAlly pipeline stages exposed as AI Agent Task tools.

Each function is one callable tool shape of the "Run ProsAlly Agent" AI Agent
Task. The LLM orchestrates the same pipeline ``ProsAllyAgent.process_message``
runs deterministically:

    classify_intent → (redirect | clarify | confirm | generate_process |
                       modify_process) → finalize

Tool shapes take no LLM arguments and don't share ``task.data`` (see
agents/shape_tools.py), so every stage reads/writes the per-turn scratch store
(agents/turn_state.py), keyed by conversation. Each terminal stage writes the
exact structured result ``run_prosally_message`` produced (intent, action_intent,
bpmn_xml, response, options, pending_xml) so "Save Response" and the canvas keep
working unchanged.

The heavy IR compile→lint→repair loop stays intact inside generate_process /
modify_process (they call ``_generate_and_validate``), so BPMN quality and the
≤3-pass repair behaviour are preserved regardless of LLM orchestration.
"""

from __future__ import annotations

import frappe

from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.google_adk.prosally_agent import tools as prosally_tools
from one_bpmn.agents.google_adk.prosally_agent.prosally_agent import ProsAllyAgent

_ACTION_INTENTS = {"GENERATE_NEW", "OVERWRITE_EXISTING", "MODIFY_EXISTING"}
_GENERATE_INTENTS = {"GENERATE_NEW", "OVERWRITE_EXISTING"}
_NEEDS_CLARIFICATION = {"AMBIGUOUS", "INCOMPLETE"}


def tool_classify_intent(conversation: str) -> dict:
    """Classify the modelling request. Call this first. If the user already
    confirmed an action (confirmed_action set), that action is adopted directly."""
    turn = get_turn(conversation)
    confirmed = (turn.get("confirmed_action") or "").strip()
    if confirmed in _ACTION_INTENTS:
        update_turn(conversation, intent=confirmed, confirmed=True)
        nxt = "generate_process" if confirmed in _GENERATE_INTENTS else "modify_process"
        return {"intent": confirmed, "already_confirmed": True, "next": nxt}

    agent = ProsAllyAgent()
    prompt = agent._build_intent_prompt(
        turn.get("user_text", ""), turn.get("process_name", ""), turn.get("chat_history", [])
    )
    raw = run_sync(agent._run("intent_classifier", prompt))
    intent, reason = "INCOMPLETE", ""
    try:
        data = agent._parse_json_response(raw)
        intent = data.get("intent", "INCOMPLETE").upper()
        reason = data.get("reason", "")
    except (ValueError, TypeError):
        pass
    if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | {"IRRELEVANT"}):
        intent = "INCOMPLETE"

    # Deterministic routing (mirrors ProsAllyAgent.process_message) so the
    # orchestrator never skips a stage: the LLM must call the tool named in "next".
    if intent == "IRRELEVANT":
        nxt = "redirect"
    elif intent in _NEEDS_CLARIFICATION:
        nxt = "clarify"
    else:  # an action intent that has NOT been confirmed yet
        nxt = "confirm"

    update_turn(conversation, intent=intent, intent_reason=reason, confirmed=False)
    return {"intent": intent, "reason": reason, "next": nxt}


def tool_redirect(conversation: str) -> dict:
    """Politely decline an off-topic request (use only when intent is IRRELEVANT)."""
    turn = get_turn(conversation)
    agent = ProsAllyAgent()
    sub_prompts = (agent._config or {}).get("sub_prompts", {})
    msg = sub_prompts.get("redirect", {}).get(
        "prompt",
        "I'm here to help with process modelling. I'm not able to help with that request.",
    )
    output = {"intent": "IRRELEVANT", "action_intent": None, "response": msg, "options": []}
    update_turn(conversation, output=output, done=True)
    return {"response": msg}


def tool_clarify(conversation: str) -> dict:
    """Ask one focused clarifying question (use when intent is AMBIGUOUS or INCOMPLETE)."""
    turn = get_turn(conversation)
    agent = ProsAllyAgent()
    prompt = agent._build_clarifier_prompt(
        turn.get("user_text", ""),
        turn.get("process_name", ""),
        turn.get("intent_reason", ""),
        turn.get("chat_history", []),
    )
    raw = run_sync(agent._run("clarifier", prompt))
    question, options = "Could you tell me more about the process you'd like to model?", []
    try:
        data = agent._parse_json_response(raw)
        question = data.get("question", question)
        options = data.get("options", [])
    except (ValueError, TypeError):
        pass
    output = {"intent": "CLARIFY", "action_intent": None, "response": question, "options": options}
    update_turn(conversation, output=output, done=True)
    return {"response": question, "options": options}


def tool_confirm(conversation: str) -> dict:
    """Summarise the intended action and ask the user to confirm before drawing
    (use for GENERATE_NEW / OVERWRITE_EXISTING / MODIFY_EXISTING that are not yet
    confirmed)."""
    turn = get_turn(conversation)
    intent = turn.get("intent", "")
    agent = ProsAllyAgent()
    raw = run_sync(
        agent._run(
            "confirmer",
            agent._build_confirmer_prompt(
                turn.get("user_text", ""), turn.get("process_name", ""), intent, turn.get("chat_history", [])
            ),
        )
    )
    try:
        data = agent._parse_json_response(raw)
        summary = data.get("summary", "")
        question = data.get("question", "Shall I proceed?")
        response_text = f"{summary}\n{question}" if summary else question
    except (ValueError, TypeError):
        response_text = raw or "Shall I proceed with this?"

    current_xml = turn.get("current_xml", "")
    if intent == "OVERWRITE_EXISTING" and current_xml.strip():
        from one_bpmn.agents.google_adk.prosally_agent.xml_property_preserver import (
            extract_configured_elements,
            summarize_configured_elements,
        )
        configured = extract_configured_elements(current_xml)
        if configured:
            response_text = f"{response_text}\n\n⚠️ **Warning:**\n{summarize_configured_elements(configured)}"

    output = {
        "intent": "CONFIRM",
        "action_intent": intent,
        "response": response_text,
        "options": ["Yes, proceed", "No, let me adjust"],
    }
    update_turn(conversation, output=output, done=True)
    return {"response": response_text, "options": output["options"]}


def tool_generate_process(conversation: str) -> dict:
    """Generate a brand-new (or overwriting) BPMN model. Use only when the action
    is GENERATE_NEW or OVERWRITE_EXISTING and the user has confirmed."""
    turn = get_turn(conversation)
    action = turn.get("intent", "GENERATE_NEW")
    if action not in _GENERATE_INTENTS:
        action = "GENERATE_NEW"
    agent = ProsAllyAgent()
    prompt = agent._build_generator_prompt(turn.get("process_name", ""), action, turn.get("chat_history", []))
    bpmn_xml, problems = run_sync(agent._generate_and_validate("process_generator", prompt))
    note = f" ({len(problems)} issue(s) remain — review the canvas.)" if problems else ""
    xml_name = prosally_tools.extract_process_name(bpmn_xml) or turn.get("process_name", "") or "process"
    output = {
        "intent": "BPMN_GENERATED",
        "action_intent": action,
        "bpmn_xml": bpmn_xml,
        "response": f"I've generated the {xml_name} process model.{note} Review it on the canvas.",
        "options": [],
    }
    update_turn(conversation, output=output, done=True)
    return {"generated": True, "process_name": xml_name, "issues": len(problems)}


def tool_modify_process(conversation: str) -> dict:
    """Modify the existing BPMN model per the conversation. Use only when the
    action is MODIFY_EXISTING and the user has confirmed."""
    turn = get_turn(conversation)
    current_xml = turn.get("current_xml", "")
    agent = ProsAllyAgent()
    prompt = agent._build_modifier_prompt(turn.get("process_name", ""), turn.get("chat_history", []), current_xml)
    bpmn_xml, problems = run_sync(agent._generate_and_validate("modifier", prompt))
    note = f" ({len(problems)} issue(s) remain — review the canvas.)" if problems else ""

    from one_bpmn.agents.google_adk.prosally_agent.xml_property_preserver import (
        transfer_properties,
        format_removal_warning,
    )
    merged_xml, removed_elements = transfer_properties(current_xml, bpmn_xml)

    if removed_elements:
        output = {
            "intent": "CONFIRM_REMOVAL",
            "action_intent": "MODIFY_EXISTING",
            "response": format_removal_warning(removed_elements),
            "options": ["Yes, apply changes", "No, keep existing"],
            "pending_xml": merged_xml,
        }
        update_turn(conversation, output=output, done=True)
        return {"modified": False, "needs_removal_confirm": True}

    xml_name = prosally_tools.extract_process_name(merged_xml) or turn.get("process_name", "") or "process"
    output = {
        "intent": "BPMN_MODIFIED",
        "action_intent": "MODIFY_EXISTING",
        "bpmn_xml": merged_xml,
        "response": (
            f"I've updated the {xml_name} process.{note} All existing configurations "
            "have been preserved. Review the changes on the canvas."
        ),
        "options": [],
    }
    update_turn(conversation, output=output, done=True)
    return {"modified": True, "process_name": xml_name, "issues": len(problems)}


def tool_finalize(conversation: str) -> dict:
    """Close the turn. Always call last. If no stage produced a reply, emits a
    safe fallback so the turn still completes."""
    turn = get_turn(conversation)
    if turn.get("done"):
        return {"finalized": True}
    output = {
        "intent": "CLARIFY",
        "action_intent": None,
        "response": "Could you tell me more about the process you'd like to model?",
        "options": [],
    }
    update_turn(conversation, output=output, done=True)
    return {"finalized": True, "fallback": True}
