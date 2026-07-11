# Copyright (c) 2026, one-fm and contributors
"""
Docu pipeline stages exposed as AI Agent Task tools.

Each function here is one callable tool shape of the "Run Docu Agent" AI Agent
Task (Camunda "tools are the shapes"). The AI Agent Task's LLM orchestrates the
same pipeline ``DocuAgent.process_message`` runs deterministically:

    classify_intent → (clarify | write_schema → review_schema) → finalize

Because tool shapes take no LLM arguments and don't share ``task.data``, every
stage reads and writes the per-turn scratch store (agents/turn_state.py), keyed
by conversation. ``finalize`` assembles the exact structured result
``run_docu_message`` produces — ``{response, intent, doctype_ir, diff, options,
suggested_name}`` — so "Save Response" and the Docu panel keep working unchanged.

The deterministic schema gate stays inside the map: ``review_schema`` runs
``validate_doctype_ir`` and refuses to mark an invalid schema approved, and
``finalize`` emits the safe-refusal output whenever the turn never produced a
validated schema — so an LLM that ignores the retry guidance can never leak an
unsafe DocType definition. Mirrors script_task_agent/stage_tools.py.
"""

from __future__ import annotations

import json

import frappe

from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.google_adk.docu_agent import tools as docu_tools
from one_bpmn.agents.google_adk.docu_agent.docu_agent import DocuAgent, _read_doctype_ir

_MAX_SECURITY_RETRIES = 3  # matches DocuAgent._MAX_FIX_PASSES

_REFUSAL = (
	"I couldn't produce a safe form definition after several attempts. "
	"Please rephrase what you'd like the form to capture and I'll try again."
)


def _fail_output(intent: str) -> dict:
	return {
		"intent": intent,
		"response": _REFUSAL,
		"doctype_ir": None,
		"diff": None,
		"options": None,
		"suggested_name": None,
	}


def _exists(doctype: str) -> bool:
	return bool(doctype) and bool(frappe.db.exists("DocType", doctype))


def tool_classify_intent(conversation: str) -> dict:
	"""Classify the request as CREATE, MODIFY, or DISAMBIGUATE. Call this first."""
	turn = get_turn(conversation)
	agent = DocuAgent()
	doctype = turn.get("doctype", "")
	exists = _exists(doctype)
	prompt = agent._build_intent_prompt(
		turn.get("user_text", ""), doctype, exists, turn.get("process_context") or {}
	)
	raw = run_sync(agent._run("intent_classifier", prompt, tools=docu_tools.CLASSIFIER_TOOLS))

	intent = "MODIFY" if exists else "CREATE"
	try:
		intent = json.loads((raw or "").strip()).get("intent", intent).upper()
	except (json.JSONDecodeError, TypeError, AttributeError):
		pass
	if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
		intent = "MODIFY" if exists else "CREATE"

	# Deterministic routing so the orchestrator never skips a stage.
	nxt = "clarify" if intent == "DISAMBIGUATE" else "write_schema"

	# Seed the MODIFY baseline once so write_schema/finalize can diff against it.
	current_ir = _read_doctype_ir(doctype) if exists else None
	update_turn(conversation, intent=intent, exists=exists, current_ir=current_ir)
	return {"intent": intent, "next": nxt}


def tool_clarify(conversation: str) -> dict:
	"""Ask one focused clarifying question (use only when intent is DISAMBIGUATE)."""
	turn = get_turn(conversation)
	agent = DocuAgent()
	raw = run_sync(
		agent._run(
			"clarifier",
			agent._build_clarifier_prompt(
				turn.get("user_text", ""), turn.get("doctype", ""), "", turn.get("chat_history", [])
			),
			tools=docu_tools.CLARIFIER_TOOLS,
		)
	)
	question, options = (raw or "Could you tell me a bit more?"), []
	try:
		# extract_json tolerates markdown-fenced or prose-wrapped JSON. A bare
		# json.loads left fenced replies unparsed, leaking the raw JSON object
		# into the chat (and dropping the clickable options).
		data = docu_tools.extract_json(raw or "")
		if isinstance(data, dict):
			question = data.get("question") or raw
			options = data.get("options") or []
	except (ValueError, json.JSONDecodeError, TypeError):
		pass

	output = {
		"intent": "DISAMBIGUATE",
		"response": question,
		"options": options,
		"doctype_ir": None,
		"diff": None,
		"suggested_name": None,
	}
	update_turn(conversation, output=output, done=True)
	return {"response": question, "options": options}


def tool_write_schema(conversation: str) -> dict:
	"""Design (or redesign) the DocType for the current request. Call after
	classify_intent for CREATE/MODIFY. If a prior review_schema reported
	violations, calling this again regenerates a corrected definition."""
	turn = get_turn(conversation)
	agent = DocuAgent()
	base_prompt = agent._build_writer_prompt(
		turn.get("user_text", ""),
		turn.get("chat_history", []),
		turn.get("doctype", ""),
		turn.get("current_ir"),
		turn.get("target_module", ""),
		turn.get("process_context") or {},
	)
	violations = turn.get("violations") or []
	prompt = base_prompt
	if violations and turn.get("draft_ir"):
		prompt = agent._build_repair_prompt(base_prompt, turn["draft_ir"], violations, [])

	draft = run_sync(agent._run("schema_writer", prompt, tools=docu_tools.WRITER_TOOLS)) or ""
	try:
		draft_ir = docu_tools.extract_json(draft)
	except (ValueError, json.JSONDecodeError):
		draft_ir = None  # writer asked a question instead of emitting JSON
	update_turn(conversation, draft_text=draft, draft_ir=draft_ir)
	return {"has_ir": bool(draft_ir), "preview": (draft or "")[:400]}


def tool_review_schema(conversation: str) -> dict:
	"""Review the drafted DocType and run the mandatory schema-safety gate.
	Returns approved/violations. If not approved, call write_schema again."""
	turn = get_turn(conversation)
	agent = DocuAgent()
	draft_ir = turn.get("draft_ir")

	# No JSON → the writer is asking a question; pass it through unvalidated.
	if not draft_ir:
		update_turn(
			conversation, final_text=turn.get("draft_text", ""), final_ir=None,
			schema_safe=True, is_question=True,
		)
		return {"approved": True, "is_question": True}

	review_raw = run_sync(agent._run("schema_reviewer", json.dumps(draft_ir), tools=docu_tools.REVIEWER_TOOLS))
	candidate = agent._apply_review(draft_ir, review_raw)
	candidate.setdefault("module", turn.get("target_module") or "ONE BPMN")

	result = docu_tools.validate_ir(candidate)
	if result["valid"]:
		update_turn(
			conversation, final_ir=candidate, final_text=turn.get("draft_text", ""),
			schema_safe=True, violations=[],
		)
		return {"approved": True, "valid": True}

	retries = int(turn.get("security_retries", 0)) + 1
	update_turn(
		conversation, draft_ir=candidate, violations=result["violations"],
		schema_safe=False, security_retries=retries,
	)
	frappe.log_error(
		title="Docu Schema Validator — " + (
			"Max retries reached" if retries > _MAX_SECURITY_RETRIES else "Regeneration requested"
		),
		message=f"Attempt {retries}\nViolations: {result['violations']}",
	)
	return {
		"approved": False,
		"valid": False,
		"violations": result["violations"],
		"fix_hints": result["fix_hints"],
		"retries_used": retries,
		"max_retries": _MAX_SECURITY_RETRIES,
	}


def tool_finalize(conversation: str) -> dict:
	"""Assemble the final structured reply for this turn. Always call last."""
	turn = get_turn(conversation)
	if turn.get("done"):  # clarify already produced the output
		return {"finalized": True}

	intent = turn.get("intent", "CREATE")

	if not turn.get("schema_safe"):
		update_turn(conversation, output=_fail_output(intent), done=True)
		return {"finalized": True, "safe": False}

	final_text = DocuAgent._response_text(turn.get("final_text", ""))
	ir = turn.get("final_ir")

	# Question passthrough (reviewer returned no JSON)
	if turn.get("is_question") or not ir:
		output = {
			"intent": intent,
			"response": final_text,
			"doctype_ir": None,
			"diff": None,
			"options": None,
			"suggested_name": None,
		}
		update_turn(conversation, output=output, done=True)
		return {"finalized": True}

	if intent == "MODIFY" and turn.get("current_ir"):
		diff = docu_tools.diff_ir(turn["current_ir"], ir)
		output = {
			"intent": "MODIFY",
			"response": final_text,
			"doctype_ir": ir,
			"diff": diff,
			"options": None,
			"suggested_name": ir.get("doctype_name") or turn.get("doctype") or None,
		}
	else:
		output = {
			"intent": "CREATE",
			"response": final_text,
			"doctype_ir": ir,
			"diff": None,
			"options": None,
			"suggested_name": ir.get("doctype_name") or turn.get("doctype") or None,
		}
	update_turn(conversation, output=output, done=True)
	return {"finalized": True}
