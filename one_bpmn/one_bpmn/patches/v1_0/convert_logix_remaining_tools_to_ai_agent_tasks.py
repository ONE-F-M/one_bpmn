"""Convert classify_intent and write_agent_tool from Script-Task wrappers into
real serviceType="ai_agent" shapes (matching clarify), finish configuring
write_script (already a bare shape but missing its prompt), and fix
review_script/finalize's broken internal LLM calls — which stay Script Tasks
(they run deterministic logic — the security validator, AST optimizer, and
several non-LLM branches — that has no declarative equivalent) but now call
their LLM step via a plain, already-safe kwargs-substitution pattern instead
of the removed aiSubAgentConfig/aiUserPromptRaw mechanism.

Nothing here needs argument-relay: build_context (untouched, main-flow Script
Task) already seeds user_text/element_name/current_script/
original_script_content/process_context/chat_history into turn state before
any tool runs, and execute_shape already auto-persists each real AI Agent
Task's own result back into turn state (shape_tools.py) — so every stage can
read what it needs via the get_turn Jinja global (hooks.py) with no
model-mediated handoff at all.
"""

import re
from xml.sax.saxutils import escape as _xml_escape
from xml.sax.saxutils import quoteattr as _quoteattr

import frappe

MODEL_NAME = "Logix – Script Task Agent"


def _attr(name, value):
	return f" spiffworkflow:{name}={_quoteattr(value)}"


# ── Shared prompt template for write_script / write_agent_tool ────────────
_WRITER_USER_PROMPT = (
	"{% set turn = get_turn(instance.context_docname) %}"
	"{% set shape_kind = turn.process_context.shape_kind | default('script_task') %}"
	"{% set is_tool = shape_kind == 'agent_tool' %}"
	"{% if turn.process_context %}**Process Context (from the BPMN diagram):**\n"
	"{% if turn.process_context.process_name %}- Process: {{ turn.process_context.process_name }}\n"
	"{% endif %}{% if is_tool %}- This element is an AGENT TOOL inside an AI Agent Task's ad-hoc Tools sub-process — an LLM calls it on demand; it is NOT a sequential process step.\n"
	"{% endif %}\n"
	"{% endif %}**Shape kind:** {{ shape_kind }}\n"
	'{% if turn.element_name %}**{{ "Agent Tool" if is_tool else "Script Task" }}:** {{ turn.element_name }}\n'
	"{% endif %}{% if turn.current_script %}**Currently linked Server Script:** {{ turn.current_script }}\n"
	"{% endif %}{% if turn.original_script_content %}**Existing script (the CURRENT code of the linked Server Script) - you are MODIFYING this. Rewrite THIS code, preserve its intent and structure, and change only what the user asked. Do NOT invent a new script from scratch:**\n"
	"```python\n{{ turn.original_script_content }}\n```\n\n"
	"{% endif %}{% if turn.chat_history %}**Conversation so far:**\n"
	'{% for m in turn.chat_history[-10:] %}{{ "User" if m.role == "user" else "Logix" }}: {{ m.content }}\n'
	"{% endfor %}\n"
	"{% endif %}{% if turn.violations %}**SECURITY REGENERATION REQUEST**\n"
	"The previous attempt was blocked by the security validator for these violations:\n"
	"{% for v in turn.violations %}  - {{ v }}\n"
	"{% endfor %}"
	"Rewrite the script WITHOUT any of these patterns. Use only `frappe.get_doc`, `frappe.db.get_value`, `frappe.get_all`, and other safe Frappe ORM methods. Do NOT import os, sys, subprocess, or any module outside the standard Frappe sandbox.\n\n"
	"{% endif %}**User request:** {{ turn.user_text }}"
)

_CLASSIFY_USER_PROMPT = (
	"{% set turn = get_turn(instance.context_docname) %}"
	"{% set shape_kind = turn.process_context.shape_kind | default('script_task') %}"
	'{% if turn.element_name %}{{ "Agent Tool" if shape_kind == "agent_tool" else "Script Task" }}: {{ turn.element_name }}\n'
	"{% endif %}{% if turn.current_script %}Linked script: {{ turn.current_script }} — existing, treat as MODIFY target unless stated otherwise\n"
	"{% else %}No script linked yet — default to CREATE\n"
	"{% endif %}Shape kind: {{ shape_kind }}\n"
	"User request: {{ turn.user_text }}"
)

_CLASSIFY_RESPONSE_SCHEMA = (
	'{"type": "object", "properties": {'
	'"intent": {"type": "string", "enum": ["CREATE", "MODIFY", "DISAMBIGUATE"]}, '
	'"shape_kind": {"type": "string", "enum": ["script_task", "agent_tool"]}, '
	'"next": {"type": "string", "enum": ["clarify", "write_script", "write_agent_tool"]}'
	'}, "required": ["intent", "shape_kind", "next"]}'
)

_NEW_CLASSIFIER_SYSTEM_PROMPT = (
	"You are an intent classifier for Logix, a BPMN Script Task AI assistant.\n\n"
	"Given a user request and task context, classify the intent as exactly one of:\n"
	"- CREATE  — user wants to write a new server script from scratch\n"
	"- MODIFY  — user wants to change, update, fix, or extend an existing linked script\n"
	"- DISAMBIGUATE — the request is vague, targets are unclear, or multiple matching scripts exist\n\n"
	"Classification rules:\n"
	'- If a script IS currently linked to the task, lean toward MODIFY unless the user clearly says "create new" or "replace".\n'
	"- If NO script is linked, lean toward CREATE unless the user references an existing script by name.\n"
	'- If the request is ambiguous AND multiple scripts could match (e.g. "update the taxes"), use DISAMBIGUATE.\n'
	"- If the request is ambiguous but there is only one plausible target, classify as MODIFY.\n\n"
	'The prompt also tells you the shape kind (script_task or agent_tool) directly — echo it back exactly as given, in the "shape_kind" field.\n\n'
	'Then compute "next" by this exact rule — never your own judgment:\n'
	'- If intent is DISAMBIGUATE: next = "clarify"\n'
	'- Else if shape_kind is "agent_tool": next = "write_agent_tool"\n'
	'- Else: next = "write_script"\n\n'
	"Respond with ONLY a JSON object — no other text:\n"
	'{"intent": "CREATE|MODIFY|DISAMBIGUATE", "shape_kind": "script_task|agent_tool", "next": "clarify|write_script|write_agent_tool"}'
)

OLD_CLASSIFIER_SYSTEM_PROMPT = (
	"You are an intent classifier for Logix, a BPMN Script Task AI assistant.\n\n"
	"Given a user request and task context, classify the intent as exactly one of:\n"
	"- CREATE  — user wants to write a new server script from scratch\n"
	"- MODIFY  — user wants to change, update, fix, or extend an existing linked script\n"
	"- DISAMBIGUATE — the request is vague, targets are unclear, or multiple matching scripts exist\n\n"
	"Classification rules:\n"
	'- If a script IS currently linked to the task, lean toward MODIFY unless the user clearly says "create new" or "replace".\n'
	"- If NO script is linked, lean toward CREATE unless the user references an existing script by name.\n"
	'- If the request is ambiguous AND multiple scripts could match (e.g. "update the taxes"), use DISAMBIGUATE.\n'
	"- If the request is ambiguous but there is only one plausible target, classify as MODIFY.\n\n"
	"Respond with ONLY a JSON object — no other text:\n"
	'{"intent": "CREATE|MODIFY|DISAMBIGUATE", "reason": "one short sentence"}'
)

CLASSIFY_OLD_TAG = (
	'<bpmn:scriptTask id="classify_intent" name="classify_intent" spiffworkflow:serverScript="Logix – Tool Classify Intent" '
	'spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Classify Intent" '
	'spiffworkflow:aiSubAgentConfig="Logix – Intent Classifier">\n'
	'        <bpmn:documentation>Classify the user request as CREATE, MODIFY, or DISAMBIGUATE. Call this FIRST.</bpmn:documentation>\n'
	'        <bpmn:script>Logix – Tool Classify Intent</bpmn:script>\n'
	'      </bpmn:scriptTask>'
)

WRITE_SCRIPT_OLD_TAG = (
	'<bpmn:serviceTask id="write_script" name="write_script" spiffworkflow:serviceType="ai_agent" '
	'spiffworkflow:aiAgentConfig="Logix – Script Writer">'
)

WRITE_AGENT_TOOL_OLD_TAG = (
	'<bpmn:scriptTask id="write_agent_tool" name="write_agent_tool" spiffworkflow:serverScript="Logix – Tool Write Agent Tool" '
	'spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Write Agent Tool" '
	'spiffworkflow:aiSubAgentConfig="Logix – Tool Writer (Agent Tools)">\n'
	'        <bpmn:documentation>Author an AGENT TOOL script (the target element lives inside an AI Agent Task\'s ad-hoc Tools sub-process). Call for CREATE or MODIFY when shape_kind is agent_tool; calling again after a failed review regenerates safe code.</bpmn:documentation>\n'
	'        <bpmn:script>Logix – Tool Write Agent Tool</bpmn:script>\n'
	'      </bpmn:scriptTask>'
)


def _build_classify_intent_new():
	attrs = (
		'id="classify_intent" name="classify_intent"'
		+ _attr("serviceType", "ai_agent")
		+ _attr("aiBackend", "direct_api")
		+ _attr("aiAgentConfig", "Logix – Intent Classifier")
		+ _attr("aiResponseFormat", "json")
		+ _attr("aiResponseSchema", _CLASSIFY_RESPONSE_SCHEMA)
		+ _attr("aiUserPrompt", _CLASSIFY_USER_PROMPT)
		+ _attr("aiTimeout", "30")
		+ _attr("aiMaxRetries", "2")
	)
	doc = "Classify the user request as CREATE, MODIFY, or DISAMBIGUATE. Call this FIRST."
	return f"<bpmn:serviceTask {attrs}>\n        <bpmn:documentation>{_xml_escape(doc)}</bpmn:documentation>\n      </bpmn:serviceTask>"


def _build_write_script_new():
	return (
		'<bpmn:serviceTask id="write_script" name="write_script"'
		+ _attr("serviceType", "ai_agent")
		+ _attr("aiBackend", "direct_api")
		+ _attr("aiAgentConfig", "Logix – Script Writer")
		+ _attr("aiResponseFormat", "text")
		+ _attr("aiUserPrompt", _WRITER_USER_PROMPT)
		+ _attr("aiTimeout", "60")
		+ _attr("aiMaxRetries", "2")
		+ ">"
	)


def _build_write_agent_tool_new():
	attrs = (
		'id="write_agent_tool" name="write_agent_tool"'
		+ _attr("serviceType", "ai_agent")
		+ _attr("aiBackend", "direct_api")
		+ _attr("aiAgentConfig", "Logix – Tool Writer (Agent Tools)")
		+ _attr("aiResponseFormat", "text")
		+ _attr("aiUserPrompt", _WRITER_USER_PROMPT)
		+ _attr("aiTimeout", "60")
		+ _attr("aiMaxRetries", "2")
	)
	doc = (
		"Author an AGENT TOOL script (the target element lives inside an AI Agent Task's ad-hoc Tools "
		"sub-process). Call for CREATE or MODIFY when shape_kind is agent_tool; calling again after a "
		"failed review regenerates safe code."
	)
	return f"<bpmn:serviceTask {attrs}>\n        <bpmn:documentation>{_xml_escape(doc)}</bpmn:documentation>\n      </bpmn:serviceTask>"


# ── review_script: fix the broken internal call, keep everything else ─────

REVIEW_SCRIPT_OLD = (
	'turn = get_turn(context_docname)\n'
	'\n'
	'draft = turn.get("draft", "")\n'
	'shape_kind = turn.get("shape_kind") or (turn.get("process_context") or {}).get("shape_kind") or "script_task"\n'
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": ai_sub_agent_config,\n'
	'    "aiUserPromptRaw": "Shape kind: " + shape_kind + "\\n\\n" + draft,\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiTimeout": 60,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'review_raw = json.loads(\n'
	'    execute_shape(instance, "review_script", _llm_task_cfg, {})\n'
	').get("review_script_output", "") or ""\n'
)
REVIEW_SCRIPT_NEW = (
	'turn = get_turn(context_docname)\n'
	'\n'
	'# write_script/write_agent_tool are now real AI Agent Task shapes with no\n'
	'# wrapper of their own — execute_shape auto-persists each one\'s result\n'
	'# under its own bpmn_id, so read whichever one actually ran.\n'
	'draft = (\n'
	'    (turn.get("write_script_result") or {}).get("write_script_output")\n'
	'    or (turn.get("write_agent_tool_result") or {}).get("write_agent_tool_output")\n'
	'    or ""\n'
	')\n'
	'shape_kind = (turn.get("process_context") or {}).get("shape_kind") or "script_task"\n'
	'_review_prompt = "Shape kind: " + shape_kind + "\\n\\n" + draft\n'
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": "Logix – Script Reviewer",\n'
	'    "aiUserPrompt": "{{ review_prompt }}",\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiTimeout": 60,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'review_raw = json.loads(\n'
	'    execute_shape(instance, "review_script", _llm_task_cfg, {"review_prompt": _review_prompt})\n'
	').get("review_script_output", "") or ""\n'
)

# ── finalize: fix the broken internal call, keep everything else ──────────

FINALIZE_OLD = (
	'                try:\n'
	'                    _llm_task_cfg = {\n'
	'                        "serviceType": "ai_agent",\n'
	'                        "aiAgentConfig": ai_sub_agent_config,\n'
	'                        "aiUserPromptRaw": test_prompt,\n'
	'                        "aiBackend": "direct_api",\n'
	'                        "aiResponseFormat": "text",\n'
	'                        "aiTimeout": 30,\n'
	'                        "aiMaxRetries": 2,\n'
	'                    }\n'
	'                    test_raw = json.loads(\n'
	'                        execute_shape(instance, "finalize", _llm_task_cfg, {})\n'
	'                    ).get("finalize_output", "") or ""\n'
)
FINALIZE_NEW = (
	'                try:\n'
	'                    _llm_task_cfg = {\n'
	'                        "serviceType": "ai_agent",\n'
	'                        "aiAgentConfig": "Logix – Test Writer",\n'
	'                        "aiUserPrompt": "{{ test_prompt }}",\n'
	'                        "aiBackend": "direct_api",\n'
	'                        "aiResponseFormat": "text",\n'
	'                        "aiTimeout": 30,\n'
	'                        "aiMaxRetries": 2,\n'
	'                    }\n'
	'                    test_raw = json.loads(\n'
	'                        execute_shape(instance, "finalize", _llm_task_cfg, {"test_prompt": test_prompt})\n'
	'                    ).get("finalize_output", "") or ""\n'
)


def execute():
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""

	changed = False
	if CLASSIFY_OLD_TAG in xml:
		xml = xml.replace(CLASSIFY_OLD_TAG, _build_classify_intent_new(), 1)
		changed = True
	elif not re.search(r'<bpmn:serviceTask\s+[^>]*id="classify_intent"', xml):
		frappe.log_error(
			title="convert_logix_remaining_tools: classify_intent anchor not found",
			message="Diverged from expected form; migrate manually.",
		)

	if WRITE_SCRIPT_OLD_TAG in xml:
		xml = xml.replace(WRITE_SCRIPT_OLD_TAG, _build_write_script_new(), 1)
		changed = True

	if WRITE_AGENT_TOOL_OLD_TAG in xml:
		xml = xml.replace(WRITE_AGENT_TOOL_OLD_TAG, _build_write_agent_tool_new(), 1)
		changed = True

	if changed:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	# Intent Classifier's system prompt needs shape_kind/next added.
	cfg = frappe.get_doc("AI Agent Configuration", "Logix – Intent Classifier")
	if cfg.system_prompt == OLD_CLASSIFIER_SYSTEM_PROMPT:
		cfg.system_prompt = _NEW_CLASSIFIER_SYSTEM_PROMPT
		cfg.save(ignore_permissions=True)

	# review_script / finalize: fix the broken internal calls.
	review_doc = frappe.get_doc("Server Script", "Logix – Tool Review Script")
	if REVIEW_SCRIPT_OLD in (review_doc.script or ""):
		review_doc.script = review_doc.script.replace(REVIEW_SCRIPT_OLD, REVIEW_SCRIPT_NEW, 1)
		review_doc.save(ignore_permissions=True)
	elif "write_script_result" not in (review_doc.script or ""):
		frappe.log_error(
			title="convert_logix_remaining_tools: review_script anchor not found",
			message="'Logix – Tool Review Script' diverged from the expected body; migrate manually.",
		)

	finalize_doc = frappe.get_doc("Server Script", "Logix – Tool Finalize")
	if FINALIZE_OLD in (finalize_doc.script or ""):
		finalize_doc.script = finalize_doc.script.replace(FINALIZE_OLD, FINALIZE_NEW, 1)
		finalize_doc.save(ignore_permissions=True)
	elif '"aiUserPrompt": "{{ test_prompt }}"' not in (finalize_doc.script or ""):
		frappe.log_error(
			title="convert_logix_remaining_tools: finalize anchor not found",
			message="'Logix – Tool Finalize' diverged from the expected body; migrate manually.",
		)

	if changed:
		from one_bpmn.api.compilation import compile_process_model

		try:
			compile_process_model(MODEL_NAME)
		except Exception:
			frappe.log_error(
				title="convert_logix_remaining_tools: recompile failed",
				message=frappe.get_traceback(),
			)
