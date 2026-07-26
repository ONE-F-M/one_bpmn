# Copyright (c) 2026, one-fm and contributors
"""
Logix pipeline stages exposed as AI Agent Task tools.

Each function here is one callable tool shape of the "Run Logix Agent" AI Agent
Task (Camunda "tools are the shapes"). The AI Agent Task's LLM orchestrates the
same pipeline ``ScriptTaskAgent.process_message`` runs deterministically:

    classify_intent → (clarify | write_script → review_script) → finalize

Because tool shapes take no LLM arguments and don't share ``task.data`` (see
agents/shape_tools.py), every stage reads and writes the per-turn scratch store
(agents/turn_state.py), keyed by conversation. ``finalize`` assembles the exact
structured result ``run_logix_message`` produced — ``{response, intent, diff,
modified_script, tests_checklist, options, suggested_name}`` — so "Save Response"
and the chat UI keep working unchanged.

The security gate stays deterministic: ``review_script`` runs the validator and
refuses to mark unsafe code approved, and ``finalize`` emits the safe-refusal
message whenever the turn never produced validated code — so an LLM that ignores
the retry guidance can never leak an unsafe script.
"""

from __future__ import annotations

import json
import re

import frappe

from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.google_adk.script_task_agent import tools as logix_tools
from one_bpmn.agents.google_adk.script_task_agent.script_task_agent import ScriptTaskAgent

_MAX_SECURITY_RETRIES = 2  # matches process_message STEP 2b (_MAX_RETRIES)

_REFUSAL = (
    "I was unable to generate a safe script after multiple attempts. "
    "Please rephrase your request to avoid forbidden operations "
    "(e.g. file access, shell commands, or raw destructive SQL)."
)


def _fail_output(intent: str) -> dict:
    return {
        "intent": intent,
        "response": _REFUSAL,
        "diff": None,
        "original_script": None,
        "modified_script": None,
        "options": None,
        "suggested_name": None,
    }


def tool_classify_intent(conversation: str) -> dict:
    """Classify the request as CREATE, MODIFY, or DISAMBIGUATE. Call this first."""
    turn = get_turn(conversation)
    agent = ScriptTaskAgent()
    current_script = turn.get("current_script", "")
    prompt = agent._build_intent_prompt(
        turn.get("user_text", ""), current_script, turn.get("element_name", "")
    )
    raw = run_sync(agent._run("intent_classifier", prompt))

    intent = "CREATE" if not current_script else "MODIFY"
    try:
        intent = json.loads((raw or "").strip()).get("intent", intent).upper()
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
        intent = "CREATE" if not current_script else "MODIFY"

    # Deterministic routing so the orchestrator never skips a stage: the LLM
    # must call the tool named in "next".
    nxt = "clarify" if intent == "DISAMBIGUATE" else "write_script"

    update_turn(conversation, intent=intent)
    return {"intent": intent, "next": nxt}


def tool_clarify(conversation: str) -> dict:
    """Ask one focused clarifying question (use only when intent is DISAMBIGUATE)."""
    turn = get_turn(conversation)
    agent = ScriptTaskAgent()
    raw = run_sync(
        agent._run(
            "clarifier",
            agent._build_intent_prompt(
                turn.get("user_text", ""),
                turn.get("current_script", ""),
                turn.get("element_name", ""),
            ),
            tools=logix_tools.CLARIFIER_TOOLS,
        )
    )
    question, options = (raw or "Could you clarify your request?"), []
    try:
        data = json.loads((raw or "").strip())
        question = data.get("question", raw)
        options = data.get("options", [])
    except (json.JSONDecodeError, TypeError):
        pass

    output = {
        "intent": "DISAMBIGUATE",
        "response": question,
        "options": options,
        "diff": None,
        "suggested_name": None,
    }
    update_turn(conversation, output=output, done=True)
    return {"response": question, "options": options}


def tool_write_script(conversation: str) -> dict:
    """Write (or rewrite) the Server Script for the current request. Call after
    classify_intent for CREATE/MODIFY. If a prior review_script reported security
    violations, calling this again automatically regenerates safe code."""
    turn = get_turn(conversation)
    agent = ScriptTaskAgent()
    prompt = agent._build_writer_prompt(
        turn.get("user_text", ""),
        turn.get("chat_history", []),
        turn.get("element_name", ""),
        turn.get("current_script", ""),
        turn.get("process_context") or {},
    )
    violations = turn.get("violations") or []
    if violations:
        prompt = agent._build_regeneration_prompt(prompt, violations)

    draft = run_sync(agent._run("script_writer", prompt, tools=logix_tools.WRITER_TOOLS))
    update_turn(conversation, draft=(draft or ""))
    has_code = bool(re.search(r"```python\s*\n.*?```", draft or "", re.DOTALL))
    return {"has_code": has_code, "preview": (draft or "")[:400]}


def tool_review_script(conversation: str) -> dict:
    """Review the drafted script and run the mandatory security gate. Returns
    approved/violations. If not approved, call write_script again (up to twice)."""
    turn = get_turn(conversation)
    agent = ScriptTaskAgent()
    draft = turn.get("draft", "")
    review_raw = run_sync(agent._run("script_reviewer", draft))
    candidate = agent._apply_review(draft, review_raw)

    # No Python block → the agent is asking a question; pass through unvalidated
    # (mirrors process_message STEP 2b).
    if not re.search(r"```python\s*\n.*?```", candidate, re.DOTALL):
        update_turn(
            conversation, final=candidate, modified_code="", script_safe=True, is_question=True
        )
        return {"approved": True, "is_question": True}

    code = agent._extract_code(candidate)
    validation = logix_tools.validate_script(code)
    if validation["valid"]:
        # Strip dead code, then re-validate so the optimizer can never bypass
        # the security gate. Keep the reply text in sync with the applied code.
        optimized = logix_tools.optimize_script(code)
        if optimized != code and logix_tools.validate_script(optimized)["valid"]:
            candidate = logix_tools.replace_code_block(candidate, optimized)
            code = optimized
        update_turn(
            conversation, final=candidate, modified_code=code, script_safe=True, violations=[]
        )
        return {"approved": True, "valid": True}

    retries = int(turn.get("security_retries", 0)) + 1
    update_turn(
        conversation,
        violations=validation["violations"],
        script_safe=False,
        security_retries=retries,
    )
    frappe.log_error(
        title="Logix Security Validator — " + (
            "Max retries reached" if retries > _MAX_SECURITY_RETRIES else "Regeneration requested"
        ),
        message=f"Attempt {retries}\nViolations: {validation['violations']}\n\nCode:\n{code}",
    )
    return {
        "approved": False,
        "valid": False,
        "violations": validation["violations"],
        "fix_hints": validation["fix_hints"],
        "retries_used": retries,
        "max_retries": _MAX_SECURITY_RETRIES,
    }


def tool_finalize(conversation: str) -> dict:
    """Assemble the final structured reply for this turn. Always call last."""
    turn = get_turn(conversation)
    if turn.get("done"):  # clarify already produced the output
        return {"finalized": True}

    intent = turn.get("intent", "CREATE")

    if not turn.get("script_safe"):
        update_turn(conversation, output=_fail_output(intent), done=True)
        return {"finalized": True, "safe": False}

    final = turn.get("final", "")
    code = turn.get("modified_code", "")

    # Question passthrough (reviewer returned no code block)
    if turn.get("is_question") or not code:
        output = {
            "intent": intent,
            "response": final,
            "diff": None,
            "original_script": None,
            "modified_script": None,
            "options": None,
            "suggested_name": None,
        }
        update_turn(conversation, output=output, done=True)
        return {"finalized": True}

    original = turn.get("original_script_content", "")
    if intent == "MODIFY" and original:
        diff = ScriptTaskAgent._compute_diff(original, code)
        output = {
            "intent": "MODIFY",
            "response": final,
            "diff": diff or None,
            "original_script": original,
            "modified_script": code,
            "options": None,
            "suggested_name": None,
        }
        update_turn(conversation, output=output, done=True)
        return {"finalized": True}

    # CREATE — generate the plain-English verification checklist (bonus; never fails the turn)
    checklist = []
    agent = ScriptTaskAgent()
    try:
        test_prompt = agent._build_test_prompt(code, turn.get("element_name", ""), turn.get("process_context") or {})
        test_raw = run_sync(agent._run("test_writer", test_prompt)) or ""
        stripped = test_raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            if stripped.endswith("```"):
                stripped = stripped[: stripped.rfind("```")].strip()
        checklist = json.loads(stripped).get("checklist", [])
    except Exception as exc:
        frappe.log_error(title="Logix test_writer parse error (stage tool)", message=str(exc))

    output = {
        "intent": "CREATE",
        "response": final,
        "diff": None,
        "original_script": None,
        "modified_script": code,
        "options": None,
        "suggested_name": turn.get("element_name") or None,
        "tests_checklist": checklist,
    }
    update_turn(conversation, output=output, done=True)
    return {"finalized": True}
