"""Experiment (per user request): convert `clarify` from a Script-Task wrapper
around execute_shape into a REAL, bare AI Agent Task shape, configured
entirely from the diagram/properties panel rather than Python. This is the
"low risk" pilot for that pattern — clarify's payload (a question + a few
options) is small enough that relaying it through the outer model is safe,
unlike write_script's potentially-hundreds-of-lines draft.

Four coordinated changes, landed together because none works alone:
1. classify_intent's result exposes user_request/element_name/current_script
   so the outer agent actually has values to relay (it never has before —
   it only ever returned intent/shape_kind/next).
2. `clarify`'s shape becomes a real serviceType="ai_agent" task: linked to
   the existing "Logix – Clarifier" config, with aiToolParams declaring the
   three relayed arguments, aiUserPrompt as a Jinja template over them, and
   structured JSON output (no more best-effort text parsing needed).
3. `finalize` gains optional clarify_question/clarify_options arguments —
   when the outer agent relays them, it builds the DISAMBIGUATE output
   directly instead of relying on turn state clarify no longer writes.
4. run_logix_agent's system prompt is updated to choreograph the new
   argument relay for the clarify step specifically.
"""

import re
from xml.sax.saxutils import escape as _xml_escape
from xml.sax.saxutils import quoteattr as _quoteattr

import frappe

MODEL_NAME = "Logix – Script Task Agent"


# ── 1. classify_intent: expose fields to relay ─────────────────────────────

CLASSIFY_OLD = (
	'update_turn(context_docname, intent=intent, shape_kind=shape_kind)\n'
	'result["intent"] = intent\n'
	'result["shape_kind"] = shape_kind\n'
	'result["next"] = nxt\n'
)
CLASSIFY_NEW = (
	'update_turn(context_docname, intent=intent, shape_kind=shape_kind)\n'
	'result["intent"] = intent\n'
	'result["shape_kind"] = shape_kind\n'
	'result["next"] = nxt\n'
	'# Exposed so the outer agent can relay them to clarify as arguments —\n'
	'# it never receives the raw conversation itself.\n'
	'result["user_request"] = message\n'
	'result["element_name"] = element_name\n'
	'result["current_script"] = current_script\n'
)


# ── 2. clarify: Script Task -> real AI Agent Task ──────────────────────────

CLARIFY_OLD = (
	'<bpmn:scriptTask id="clarify" name="clarify" spiffworkflow:serverScript="Logix – Tool Clarify" '
	'spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Clarify" '
	'spiffworkflow:aiSubAgentConfig="Logix – Clarifier">\n'
	'        <bpmn:documentation>Ask one focused clarifying question. Use ONLY when intent is DISAMBIGUATE.</bpmn:documentation>\n'
	'        <bpmn:script>Logix – Tool Clarify</bpmn:script>\n'
	'      </bpmn:scriptTask>'
)

_CLARIFY_USER_PROMPT = (
	"{% if element_name %}Script Task: {{ element_name }}\n"
	"{% endif %}{% if current_script %}Linked script: {{ current_script }} — existing, treat as MODIFY target unless stated otherwise\n"
	"{% else %}No script linked yet — default to CREATE\n"
	"{% endif %}User request: {{ user_request }}"
)
_CLARIFY_TOOL_PARAMS = (
	'{"properties": {'
	'"user_request": {"type": "string", "description": "The user\'s raw request text (from classify_intent\'s result)."}, '
	'"element_name": {"type": "string", "description": "Label of the target Script Task/Agent Tool element, if known (from classify_intent\'s result)."}, '
	'"current_script": {"type": "string", "description": "Name of the currently linked Server Script, if any (from classify_intent\'s result)."}'
	'}, "required": ["user_request"]}'
)
_CLARIFY_RESPONSE_SCHEMA = (
	'{"type": "object", "properties": {'
	'"question": {"type": "string"}, '
	'"options": {"type": "array", "items": {"type": "string"}}'
	'}, "required": ["question", "options"]}'
)


def _attr(name, value):
	# quoteattr picks whichever quote delimiter (' or ") needs the least
	# escaping for this value and applies it correctly either way — safer
	# here than forcing " given these values mix apostrophes (descriptions)
	# and literal double quotes (JSON schemas), either of which a naive
	# hand-rolled escape is liable to mangle.
	return f" spiffworkflow:{name}={_quoteattr(value)}"


def _build_clarify_new():
	attrs = (
		'id="clarify" name="clarify"'
		+ _attr("serviceType", "ai_agent")
		+ _attr("aiBackend", "direct_api")
		+ _attr("aiAgentConfig", "Logix – Clarifier")
		+ _attr("aiResponseFormat", "json")
		+ _attr("aiResponseSchema", _CLARIFY_RESPONSE_SCHEMA)
		+ _attr("aiUserPrompt", _CLARIFY_USER_PROMPT)
		+ _attr("aiToolParams", _CLARIFY_TOOL_PARAMS)
		+ _attr("aiTimeout", "30")
		+ _attr("aiMaxRetries", "2")
	)
	doc = (
		"Ask one focused clarifying question. Use ONLY when intent is DISAMBIGUATE. "
		"Pass user_request (required), element_name and current_script (from classify_intent's "
		"result) as arguments."
	)
	return (
		f"<bpmn:serviceTask {attrs}>\n"
		f"        <bpmn:documentation>{_xml_escape(doc)}</bpmn:documentation>\n"
		f"      </bpmn:serviceTask>"
	)


# ── 3. finalize: accept the relayed clarify answer ─────────────────────────

FINALIZE_OLD = (
	'turn = get_turn(context_docname)\n'
	'if turn.get("done"):  # clarify already produced the output\n'
	'    result["finalized"] = True\n'
	'else:\n'
)
FINALIZE_NEW = (
	'turn = get_turn(context_docname)\n'
	'_clarify_question = task_data.get("clarify_question")\n'
	'if _clarify_question:\n'
	'    # Relayed directly from clarify\'s own AI Agent Task result — no\n'
	'    # turn-state round trip needed; clarify is no longer a Script Task\n'
	'    # and never calls update_turn itself.\n'
	'    update_turn(context_docname, output={\n'
	'        "intent": "DISAMBIGUATE", "response": _clarify_question, "diff": None,\n'
	'        "original_script": None, "modified_script": None,\n'
	'        "options": task_data.get("clarify_options") or [], "suggested_name": None,\n'
	'    }, done=True)\n'
	'    result["finalized"] = True\n'
	'elif turn.get("done"):  # legacy path: pre-migration turn-state handoff\n'
	'    result["finalized"] = True\n'
	'else:\n'
)

FINALIZE_TOOL_PARAMS = (
	'{"properties": {'
	'"clarify_question": {"type": "string", "description": "The clarifying question clarify asked, to relay to the user (only when next was clarify)."}, '
	'"clarify_options": {"type": "array", "items": {"type": "string"}, "description": "The option list clarify offered, to relay to the user."}'
	'}, "required": []}'
)


# ── 4. run_logix_agent: choreograph the new relay ──────────────────────────

ORCH_OLD = "if next is clarify, call clarify then call finalize and stop."
ORCH_NEW = (
	"if next is clarify, call clarify passing user_request, element_name and current_script "
	"(from classify_intent's result) as arguments, then call finalize passing clarify's own "
	"question and options as clarify_question and clarify_options arguments, then stop."
)


def execute():
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if "clarify_question" in xml:
		return  # already migrated

	if CLARIFY_OLD not in xml:
		frappe.log_error(
			title="convert_logix_clarify_to_ai_agent_task: clarify anchor not found",
			message="'clarify' shape tag diverged from the expected form; migrate manually.",
		)
		return
	if ORCH_OLD not in xml:
		frappe.log_error(
			title="convert_logix_clarify_to_ai_agent_task: orchestration anchor not found",
			message="run_logix_agent's aiSystemPrompt diverged from the expected form; migrate manually.",
		)
		return

	xml = xml.replace(CLARIFY_OLD, _build_clarify_new(), 1)
	xml = xml.replace(ORCH_OLD, ORCH_NEW, 1)

	# Add finalize's new optional aiToolParams — its shape tag currently has
	# none, so append the attribute rather than editing an existing one.
	m = re.search(r'<bpmn:scriptTask\s+[^>]*id="finalize"[^>]*>', xml)
	if not m:
		frappe.log_error(
			title="convert_logix_clarify_to_ai_agent_task: finalize anchor not found",
			message="'finalize' shape tag not found; migrate manually.",
		)
		return
	old_finalize_tag = m.group(0)
	new_finalize_tag = old_finalize_tag[:-1] + _attr("aiToolParams", FINALIZE_TOOL_PARAMS) + ">"
	xml = xml.replace(old_finalize_tag, new_finalize_tag, 1)

	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	classify_doc = frappe.get_doc("Server Script", "Logix – Tool Classify Intent")
	if CLASSIFY_OLD in (classify_doc.script or ""):
		classify_doc.script = classify_doc.script.replace(CLASSIFY_OLD, CLASSIFY_NEW, 1)
		classify_doc.save(ignore_permissions=True)
	else:
		frappe.log_error(
			title="convert_logix_clarify_to_ai_agent_task: classify_intent anchor not found",
			message="'Logix – Tool Classify Intent' diverged from the expected body; migrate manually.",
		)

	finalize_doc = frappe.get_doc("Server Script", "Logix – Tool Finalize")
	if FINALIZE_OLD in (finalize_doc.script or ""):
		finalize_doc.script = finalize_doc.script.replace(FINALIZE_OLD, FINALIZE_NEW, 1)
		finalize_doc.save(ignore_permissions=True)
	else:
		frappe.log_error(
			title="convert_logix_clarify_to_ai_agent_task: finalize anchor not found",
			message="'Logix – Tool Finalize' diverged from the expected body; migrate manually.",
		)

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="convert_logix_clarify_to_ai_agent_task: recompile failed",
			message=frappe.get_traceback(),
		)
