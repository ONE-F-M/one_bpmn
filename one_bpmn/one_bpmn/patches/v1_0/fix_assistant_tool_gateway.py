"""
WI-001751 follow-up: stop the AI Assistant's tool gateway from crashing every turn.

Symptom: every message to the assistant from the AI Agent Task dialog died with
"The process for agent 'ai_agent_assistant' is not running for this
conversation. Please reopen the chat." The instance was in fact Errored inside
50ms of starting, with:

    Error evaluating expression '(agent_decision2 or {}).get("needs_tool") == True'
    AttributeError: 'str' object has no attribute 'get'

Cause: fix_assistant_response_contract (same WI) removed aiResponseFormat="json"
and the {needs_tool, final_answer} schema from the assistant's ai_agent_task,
leaving it aiResponseFormat="text". Its output variable (agent_decision2) is
therefore always a plain string. But the "Needs to call tools?" exclusive
gateway immediately downstream still calls .get("needs_tool") on that variable.
The producer of the flag was removed; the consumer was not.

The `(agent_decision2 or {})` guard only rescues None and the empty string — any
real reply falls straight through to .get() and raises. The gateway's default
flow cannot save it either: the exception is raised while EVALUATING the
condition, before SpiffWorkflow ever gets to pick a branch. So the failure is
deterministic on every turn that produces text.

Fix: make the condition type-safe.

    isinstance(<var>, dict) and <var>.get("needs_tool") == True

Under aiResponseFormat="text" that is always False, so the gateway takes its
default flow (save the response) — which is the intended behaviour now that the
tool loop runs INSIDE the AI Agent Task rather than being orchestrated by the
diagram. The branch is left in place rather than deleted: it costs nothing, it
keeps the diagram readable against the other chat maps, and it starts working
again by itself if a JSON contract is ever restored on that shape.
isinstance is available because the engine's TaskDataEnvironment does not
restrict __builtins__ (see engine.get_script_engine).

Only the assistant's own map is touched — Docu, Logix and ProsAlly use a bare
`needs_tools == True` condition and are unaffected.

Diagrams are data, never code (WI-001540), so the repair is applied to the
site's own copy of the map. Idempotent: matching is on the broken shape of the
expression, so a second run finds nothing to do.
"""

import re

import frappe

MODEL_NAME = "AI Agent Assistant — Chat"

# `(<var> or {}).get("needs_tool")` — the variable name is captured rather than
# hardcoded so a site whose map uses a different output variable is still
# repaired. Quotes may be either style inside the BPMN attribute.
_BROKEN = re.compile(
	r"""\(\s*(?P<var>[A-Za-z_]\w*)\s+or\s+\{\}\s*\)\s*\.get\(\s*(?P<q>['"])needs_tool(?P=q)\s*\)"""
)


def _repair(expression: str) -> str:
	return _BROKEN.sub(
		lambda m: f"isinstance({m.group('var')}, dict) and {m.group('var')}.get(\"needs_tool\")",
		expression,
	)


def execute():
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		frappe.log_error(
			title="fix_assistant_tool_gateway: assistant map missing",
			message=f"No BPMN Process Model '{MODEL_NAME}' on this site; nothing to repair.",
		)
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if not _BROKEN.search(xml):
		return  # already repaired, or this site's map never had the broken form

	repaired = _repair(xml)
	if repaired == xml:
		return

	# db_set skips the editability gate — a trusted content migration, the same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", repaired)

	# Recompile so serialized_spec carries the fixed condition. New conversations
	# pick it up; instances already Errored stay Errored and are simply replaced
	# when the user reopens the chat.
	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="fix_assistant_tool_gateway: recompile failed",
			message=frappe.get_traceback(),
		)

	frappe.db.commit()
