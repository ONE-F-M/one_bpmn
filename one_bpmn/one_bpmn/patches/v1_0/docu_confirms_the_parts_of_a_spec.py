"""Docu lists the parts of a multi-department spec, confirms them, and says which parts the DocType covers.

The classifier names the parts, Classify Intent asks the person to confirm them before anything is written,
the writer is told to cover each one, and Finalize names any part its reply leaves out.
Each anchor must be found exactly once; anything else is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import _edit_script, apply_edit

AGENT_ID = "docu_agent"
MODEL_NAME = "Docu \u2013 DocType Agent"
CONFIRM = "Yes, cover all of these"

RULE_ANCHOR = "\n\nRespond with ONLY a JSON object \u2014 no other text:\n"
RULE = (
	"\n- PARTS: when the request is a spec that hands work to two or more departments, roles or sections "
	'("Payroll enters ..., Procurement checks ..., Finance confirms ..."), list them in "parts", one short '
	"name each, in the order the spec gives them. Otherwise return an empty list."
)
SHAPE_ANCHOR = '"reason": "one short sentence"}'
SHAPE = '"reason": "one short sentence", "parts": ["part name", ...]}'

PENDING_ANCHOR = 'message = turn.get("user_text", "")\n'
PENDING = PENDING_ANCHOR + (
	"\n# A reply to the parts question carries the spec it was asked about.\n"
	"import re\n"
	"from one_bpmn.agents.memory.session_state import record\n"
	'_state = turn.get("session_state") or {}\n'
	"_confirmed = []\n"
	"_found = []\n"
	'if _state.get("pending_parts"):\n'
	'    if re.match(r"\\s*(yes|yep|yeah|ok|okay|correct|confirm|go ahead|looks good)\\b", message, re.IGNORECASE):\n'
	'        _confirmed = _state.get("pending_parts")\n'
	'        message = _state.get("pending_spec") or message\n'
	"    else:\n"
	'        message = (_state.get("pending_spec") or "") + "\\n\\nChange to the list of parts: " + message\n'
	'    record(context_docname, {"pending_parts": None, "pending_spec": None})\n'
	"    update_turn(context_docname, user_text=message, parts=_confirmed)\n"
)

PARSE_ANCHOR = '    try:\n        intent = json.loads((raw or "").strip()).get("intent", intent).upper()\n'
PARSE = (
	"    try:\n"
	'        _data = json.loads((raw or "").strip())\n'
	'        _found = _data.get("parts") or []\n'
	'        intent = _data.get("intent", intent).upper()\n'
)

ASK_ANCHOR = "if intent in _cheap_intents:\n"
ASK = (
	'if intent in ("CREATE", "MODIFY") and not _confirmed and isinstance(_found, list) and len(_found) > 1:\n'
	'    _ask = ("Your spec has these parts:\\n- " + "\\n- ".join([str(_p) for _p in _found])\n'
	'            + "\\n\\nShall I cover all of them? If a part is missing or should not be there, tell me what to change.")\n'
	'    record(context_docname, {"pending_parts": [str(_p) for _p in _found], "pending_spec": message})\n'
	"    update_turn(\n"
	"        context_docname,\n"
	"        intent=intent,\n"
	"        exists=exists,\n"
	"        output={\n"
	'            "intent": "DISAMBIGUATE",\n'
	'            "response": _ask,\n'
	f'            "options": ["{CONFIRM}"],\n'
	'            "doctype_ir": None,\n'
	'            "diff": None,\n'
	'            "suggested_name": None,\n'
	"        },\n"
	"        done=True,\n"
	"    )\n"
	'    result["intent"] = intent\n'
	'    result["next"] = None\n'
	'    result["response"] = _ask\n'
	"elif intent in _cheap_intents:\n"
)

MISSING_ANCHOR = '        ir = turn.get("final_ir")\n'
MISSING = (
	"        _missing = []\n"
	'        for _p in (turn.get("parts") or []):\n'
	"            if str(_p).lower() not in final_text.lower():\n"
	"                _missing.append(str(_p))\n"
	"        if _missing:\n"
	'            final_text += "\\n\\nNot covered yet: " + ", ".join(_missing) + "."\n'
) + MISSING_ANCHOR

# Raw bpmn_xml text of the write_schema prompt, attribute escaping included.
WRITER_ANCHOR = "{% endif %}**User request:** {{ turn.user_text }}"
WRITER = (
	"{% endif %}{% if turn.parts %}The spec has these parts and the person confirmed all of them: "
	"{{ turn.parts | join(&#39;, &#39;) }}. Cover every one. In your reply give each part its own line, "
	"using the part name exactly as written here, and say what you added for it or that you did not "
	"cover it.&#10;&#10;{% endif %}**User request:** {{ turn.user_text }}"
)


def execute():
	_edit_prompt()
	_edit_script("docu_tool_classify_intent", PENDING_ANCHOR, PENDING)
	_edit_script("docu_tool_classify_intent", PARSE_ANCHOR, PARSE)
	_edit_script("docu_tool_classify_intent", ASK_ANCHOR, ASK)
	_edit_script("docu_tool_finalize", MISSING_ANCHOR, MISSING)
	_edit_map()


def _edit_prompt():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not agent:
		return
	row = frappe.db.get_value(
		"AI Agent Sub Prompt",
		{"parent": agent, "sub_agent_id": "intent_classifier"},
		["name", "prompt_text"],
		as_dict=True,
	)
	text = (row or {}).get("prompt_text") or ""
	for anchor, replacement in ((RULE_ANCHOR, RULE + RULE_ANCHOR), (SHAPE_ANCHOR, SHAPE)):
		edited = apply_edit(text, anchor, replacement)
		if edited is None:
			frappe.log_error(
				title="docu_confirms_the_parts_of_a_spec: anchor not found",
				message=f"intent_classifier has no single '{anchor}'; the prompt is left as-is.",
			)
			return
		text = edited
	if text != row.prompt_text:
		frappe.db.set_value("AI Agent Sub Prompt", row.name, "prompt_text", text)
		frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def _edit_map():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if not xml:
		return
	edited = apply_edit(xml, WRITER_ANCHOR, WRITER)
	if edited is None:
		frappe.log_error(
			title="docu_confirms_the_parts_of_a_spec: anchor not found",
			message=f"{MODEL_NAME} has no single write_schema user request line; the map is left as-is.",
		)
		return
	if edited == xml:
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", edited)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(MODEL_NAME)
