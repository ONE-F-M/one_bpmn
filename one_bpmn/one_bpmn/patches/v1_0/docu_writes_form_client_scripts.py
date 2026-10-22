"""Docu routes a request for form behaviour to a client script stage.

The classifier gains EDIT_CLIENT_SCRIPT and routes it to the edit_client_script stage. Idempotent: every
replacement checks for its own result first, and a site without Docu is left alone.
"""

import re

import frappe

AGENT_ID = "docu_agent"
CLASSIFY = "Docu – Tool Classify Intent"

INTENT_ANCHOR = "\n- DISAMBIGUATE "
INTENT_RULE = (
	"\n- EDIT_CLIENT_SCRIPT: the user wants an existing form to behave in a way a field setting cannot "
	"express: react when a field changes, fill or clear a field from another, add a button, filter the "
	'choices of a link field, or warn before saving ("when Status is Closed, clear the Assignee", '
	'"add a button that opens the linked invoice"). Only showing, hiding, requiring or locking a field '
	"is EDIT_FIELD_PROPERTY. A form the user names or has selected is enough."
)
ENUM_OLD = "EDIT_FIELD_PROPERTY|DISAMBIGUATE|"
ENUM_NEW = "EDIT_FIELD_PROPERTY|EDIT_CLIENT_SCRIPT|DISAMBIGUATE|"

ACCEPT_OLD = 'if intent not in ("CREATE", "MODIFY", "EDIT_FIELD_PROPERTY", "DISAMBIGUATE")'
ACCEPT_NEW = 'if intent not in ("CREATE", "MODIFY", "EDIT_FIELD_PROPERTY", "EDIT_CLIENT_SCRIPT", "DISAMBIGUATE")'
ROUTE_OLD = '{"DISAMBIGUATE": "clarify", "EDIT_FIELD_PROPERTY": "edit_field_property"}'
ROUTE_NEW = (
	'{"DISAMBIGUATE": "clarify", "EDIT_FIELD_PROPERTY": "edit_field_property", '
	'"EDIT_CLIENT_SCRIPT": "edit_client_script"}'
)

SYSTEM_OLD = "call edit_field_property, then finalize, then stop."
SYSTEM_NEW = SYSTEM_OLD + " If next is edit_client_script: call edit_client_script, then finalize, then stop."


MAP = "Docu – DocType Agent"
STAGE = "edit_client_script"
STAGE_SCRIPT = "Docu – Tool Edit Client Script"
SUB_AGENT_ID = "client_script_writer"

WRITER_PROMPT = """You write one Frappe Form View client script for an existing form, for a process owner who is not a developer.
You are given the form's fields as "fieldname | type | label | options", the form's current script if it has one, the conversation so far and the user's request.

If the request leaves out something you need (which field, which value, when it should happen), ask ONE short question with 2 to 4 plain-English options. Otherwise write the script.

Script rules:
- Start from frappe.ui.form.on("<Form>", { ... }) using the form name you are given.
- Use only fieldnames from the list. Never invent one.
- Use the frm argument, never cur_frm. Use frm.set_value, frm.toggle_display, frm.toggle_reqd, frm.toggle_enable, frm.set_query, frm.add_custom_button and frappe.call. Never use eval, fetch, XMLHttpRequest, browser storage, console.log or inline styles.
- Double quotes. Wrap every message the user will read in __("").
- Block a save by calling frappe.throw(__("...")) inside the validate handler.
- When a current script is shown, return the COMPLETE script: keep every handler you are not asked to change exactly as it is.
- Showing, hiding, requiring or locking a field depending on another field does not belong in a script; say so in a question.

Respond with ONLY a JSON object, either
{"question": "...", "options": ["...", "..."]}
or
{"script": "<the full script>", "summary": "one or two plain sentences saying what the form will now do"}"""

STAGE_SCRIPT_BODY = r"""# Docu - Tool Edit Client Script (self-contained, FLAT top-level code; no def/lambda under the shape-tool exec).
# Drafts a Form View client script for the form or asks one question; nothing is saved until the person applies it.
import difflib
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.prosally_helpers import extract_json
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.security.client_script_validator import validate_form_script

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
message = turn.get("user_text", "")
doctype = turn.get("doctype", "")

output = {
    "intent": "EDIT_CLIENT_SCRIPT",
    "mode": "CREATE",
    "response": "",
    "modified_script": None,
    "diff": None,
    "apply_target": None,
    "suggested_name": None,
    "doctype_ir": None,
    "options": None,
}

if not (doctype and frappe.db.exists("DocType", doctype)):
    output["intent"] = "DISAMBIGUATE"
    output["response"] = "Which form should this script go on? Select it on the step, or tell me its name."
else:
    _rows = []
    for _f in frappe.get_meta(doctype).fields:
        if _f.fieldtype in ("Section Break", "Column Break", "Tab Break"):
            continue
        _opts = (_f.options or "").replace("\n", ",")[:120]
        _rows.append(_f.fieldname + " | " + _f.fieldtype + " | " + (_f.label or "") + " | " + _opts)
    _existing = frappe.db.get_value("Client Script", {"dt": doctype, "view": "Form"}, "script") or ""

    _hlines = []
    for _e in (turn.get("chat_history") or [])[-10:]:
        _role = _e.get("role") or _e.get("type", "user")
        _content = (_e.get("content") or "").strip()
        if _content:
            _hlines.append(("User" if _role == "user" else "Docu") + ": " + _content)

    _parts = ["Form: " + doctype, "Fields:\n" + "\n".join(_rows)]
    if _existing:
        _parts.append("Current script:\n" + _existing)
    if _hlines:
        _parts.append("Conversation so far:\n" + "\n".join(_hlines))
    _parts.append("User request: " + message)
    prompt = "\n\n".join(_parts)

    _system = (_subs.get("client_script_writer") or {}).get("prompt") or ""
    _adapter = get_llm_adapter_from_settings(_cfg)
    data = {}
    script = ""
    problems = []
    _feedback = ""
    for _attempt in range(2):
        data = extract_json(run_sync(_adapter.complete(system=_system, user=prompt + _feedback)).text) or {}
        if data.get("question"):
            break
        script = (data.get("script") or "").strip()
        problems = validate_form_script(doctype, script) if script else ["The reply had no script."]
        if not problems:
            break
        _feedback = "\n\nYour last script was refused:\n- " + "\n- ".join(problems) + "\nReturn the corrected JSON."
        script = ""

    if data.get("question"):
        output["intent"] = "DISAMBIGUATE"
        output["response"] = data["question"]
        output["options"] = data.get("options") or []
    elif script:
        _diff = []
        if _existing:
            output["mode"] = "MODIFY"
            _old = _existing.splitlines()
            _new = script.splitlines()
            for _tag, _i1, _i2, _j1, _j2 in difflib.SequenceMatcher(None, _old, _new).get_opcodes():
                if _tag != "equal":
                    _kind = {"replace": "changed", "delete": "deleted", "insert": "added"}[_tag]
                    _diff.append({"type": _kind, "left": "\n".join(_old[_i1:_i2]), "right": "\n".join(_new[_j1:_j2])})
        output["modified_script"] = script + "\n"
        output["diff"] = _diff or None
        output["apply_target"] = doctype
        output["suggested_name"] = doctype + "-Form"
        output["response"] = (data.get("summary") or "Here is the script for " + doctype + ".") + " Review it below and press Apply to save it to the form."
    else:
        output["response"] = "I could not write a safe script for that. " + " ".join(problems) + " Tell me a little more about what the form should do and I will try again."

update_turn(context_docname, intent=output["intent"], output=output, done=True)
result["response"] = output["response"]
"""

SHAPE = (
	f'<bpmn:scriptTask id="{STAGE}" name="{STAGE}" spiffworkflow:serverScript="{STAGE_SCRIPT}"'
	f' spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="{STAGE_SCRIPT}">\n'
	"        <bpmn:documentation>Draft a Form View client script for the form, or ask one question, and reply with "
	"the script for the person to apply. Call only when classify_intent returns next edit_client_script."
	"</bpmn:documentation>\n"
	f"        <bpmn:script>{STAGE_SCRIPT}</bpmn:script>\n"
	"      </bpmn:scriptTask>\n"
	"    "
)
SHAPE_DI = (
	f'<bpmndi:BPMNShape id="{STAGE}_di" bpmnElement="{STAGE}">\n'
	'        <dc:Bounds x="920" y="660" width="100" height="70" />\n'
	"      </bpmndi:BPMNShape>\n"
	"    "
)
TOOLS_BOUNDS = re.compile(r'(bpmnElement="docu_tools" isExpanded="true">\s*<dc:Bounds x="900" y="320" width="550" height=")340"')


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name or not frappe.db.exists("Server Script", CLASSIFY):
		return
	_set_config(name)
	if not frappe.db.exists("Server Script", STAGE_SCRIPT):
		frappe.get_doc(
			{"doctype": "Server Script", "name": STAGE_SCRIPT, "script_type": "API", "script": STAGE_SCRIPT_BODY}
		).insert(ignore_permissions=True)
	if _add_shape():
		_route_from_classifier()


def _set_config(name):
	doc = frappe.get_doc("AI Agent Configuration", name)
	if SYSTEM_NEW not in (doc.system_prompt or ""):
		doc.system_prompt = (doc.system_prompt or "").replace(SYSTEM_OLD, SYSTEM_NEW, 1)
	for row in doc.sub_prompts:
		text = row.prompt_text or ""
		if row.sub_agent_id == "intent_classifier" and "EDIT_CLIENT_SCRIPT" not in text:
			row.prompt_text = text.replace(INTENT_ANCHOR, INTENT_RULE + INTENT_ANCHOR, 1).replace(
				ENUM_OLD, ENUM_NEW, 1
			)
	if not any(row.sub_agent_id == SUB_AGENT_ID for row in doc.sub_prompts):
		doc.append(
			"sub_prompts",
			{
				"sub_agent_id": SUB_AGENT_ID,
				"sub_agent_name": "Client Script Writer",
				"temperature": 0.2,
				"prompt_text": WRITER_PROMPT,
			},
		)
	doc.save(ignore_permissions=True)


def _add_shape():
	"""Put the stage in a new bottom row of the map's Tools sub-process, recompile, and say whether it is there."""
	from one_bpmn.api.compilation import compile_process_model

	if not frappe.db.exists("BPMN Process Model", MAP):
		return False
	model = frappe.get_doc("BPMN Process Model", MAP)
	xml = model.bpmn_xml or ""
	if f'id="{STAGE}"' in xml:
		return True
	if xml.count("</bpmn:adHocSubProcess>") != 1 or xml.count("</bpmndi:BPMNPlane>") != 1 or not TOOLS_BOUNDS.search(xml):
		frappe.log_error(
			title="docu_writes_form_client_scripts: map shape not added",
			message=f"{MAP} does not have the expected Tools sub-process and diagram plane.",
		)
		return False
	xml = TOOLS_BOUNDS.sub(r'\g<1>440"', xml)
	xml = xml.replace("</bpmn:adHocSubProcess>", SHAPE + "</bpmn:adHocSubProcess>")
	model.bpmn_xml = xml.replace("</bpmndi:BPMNPlane>", SHAPE_DI + "</bpmndi:BPMNPlane>")
	model.save(ignore_permissions=True)
	compile_process_model(MAP)
	return True


def _route_from_classifier():
	script = frappe.db.get_value("Server Script", CLASSIFY, "script") or ""
	if ROUTE_NEW in script or ROUTE_OLD not in script or ACCEPT_OLD not in script:
		return
	frappe.db.set_value(
		"Server Script",
		CLASSIFY,
		"script",
		script.replace(ACCEPT_OLD, ACCEPT_NEW, 1).replace(ROUTE_OLD, ROUTE_NEW, 1),
	)
