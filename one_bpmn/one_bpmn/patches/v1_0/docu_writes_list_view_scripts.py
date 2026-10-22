"""Docu creates and updates the List View Client Script on a DocType, after the person confirms it.

The classifier gains LIST_VIEW_SCRIPT and routes it to a write_list_script stage. The stage drafts the
script, keeps it in session state and asks for a yes; the next turn applies it through
apply_list_view_script. A reply while a draft is pending is routed back to the stage, ahead of the
small-talk test, so a bare "yes" is not taken for a greeting. Idempotent: every edit checks for its own result.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import _edit_script

AGENT_ID = "docu_agent"
MAP = "Docu \u2013 DocType Agent"
WRITE_SCRIPT = "Docu - Tool Write List Script"
SUB_AGENT_ID = "list_script_writer"
CLASSIFY_API = "docu_tool_classify_intent"

INTENT_ANCHOR = "\n- DISAMBIGUATE "
INTENT_RULE = (
	"\n- LIST_VIEW_SCRIPT: the user wants the list of an existing DocType to behave or look differently: "
	"extra columns, coloured status indicators, row formatting, a button above the list, or a default "
	'filter ("show the status as a coloured tag in the Leave Request list"). It changes how records are '
	"listed, never which fields the DocType has. Name the DocType in your reason."
)
ENUM_OLD = "|EDIT_FIELD_PROPERTY|DISAMBIGUATE|"
ENUM_NEW = "|EDIT_FIELD_PROPERTY|LIST_VIEW_SCRIPT|DISAMBIGUATE|"

SYSTEM_OLD = "If next is edit_field_property: call edit_field_property, then finalize, then stop."
SYSTEM_NEW = SYSTEM_OLD + " If next is write_list_script: call write_list_script, then finalize, then stop."

ACCEPT_OLD = '"MODIFY", "EDIT_FIELD_PROPERTY", "DISAMBIGUATE")'
ACCEPT_NEW = '"MODIFY", "EDIT_FIELD_PROPERTY", "LIST_VIEW_SCRIPT", "DISAMBIGUATE")'
ROUTE_OLD = '"EDIT_FIELD_PROPERTY": "edit_field_property"}'
ROUTE_NEW = '"EDIT_FIELD_PROPERTY": "edit_field_property", "LIST_VIEW_SCRIPT": "write_list_script"}'
PENDING_OLD = 'intent = "SMALL_TALK" if _small_talk else ""\n'
PENDING_NEW = (
	'_pending_list = (turn.get("session_state") or {}).get("pending_list_script")\n'
	'intent = "LIST_VIEW_SCRIPT" if _pending_list else ("SMALL_TALK" if _small_talk else "")\n'
)

WRITER_PROMPT = """You write the List View Client Script for one Frappe DocType, from a business user's request.
You are given the DocType's fields as "fieldname | type | label", the current list script if there is one, and the request.

The script must be one assignment, frappe.listview_settings["<DocType>"] = { ... };, and may use only these settings:
- add_fields: ["fieldname", ...] the fields the list loads so the other settings can read them.
- get_indicator: function(doc) { return [__("Label"), "green|red|orange|blue|gray|yellow", "fieldname,=,value"]; } a coloured status tag.
- formatters: { fieldname: function(value, df, doc) { return ...; } } how a column value is shown.
- hide_name_column: true hides the ID column.
- filters: [["fieldname", "=", "value"]] a default filter.
- onload: function(listview) { listview.page.add_inner_button(__("Label"), function() { ... }); } a button above the list.
- button: { show: function(doc) { return ...; }, get_label: function() { return __("Label"); }, get_description: function(doc) { return __("Text"); }, action: function(doc) { ... } } a button on each row.

Hard limits: no network calls, eval, cookies, storage, redirects, external URLs or script tags. Use only fieldnames from the list. Wrap every label in __().
When there is a current script, return the COMPLETE new script: keep every setting the request does not change.

Ask a question instead of writing when the request does not say which DocType, or which fields or values it means. One short plain English question, never mentioning code.

Respond with ONLY a JSON object:
{"doctype": "the DocType name", "script": "the full script, or an empty string when you ask a question", "summary": "one or two plain English sentences of what changes in the list, for a non-technical person", "question": "your question, or an empty string"}"""

WRITE_SCRIPT_BODY = r"""# Docu - Tool Write List Script (self-contained, FLAT top-level code; no def/lambda under the shape-tool exec).
# Drafts a List View Client Script, keeps it pending until the person says yes, then applies it.
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.memory.session_state import record
from one_bpmn.agents.prosally_helpers import extract_json
from one_bpmn.api.docu_api import apply_list_view_script, get_list_view_script
from one_bpmn.security.client_script_validator import validate_list_view_script
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
message = turn.get("user_text", "")
doctype = turn.get("doctype", "")
_pending = (turn.get("session_state") or {}).get("pending_list_script") or {}
_options = None
reply = ""
_draft = True

if _pending:
    if re.match(r"\s*(yes|yep|yeah|ok|okay|correct|confirm|go ahead|apply|looks good)\b", message, re.IGNORECASE):
        _draft = False
        record(context_docname, {"pending_list_script": None})
        try:
            _done = apply_list_view_script(_pending["doctype"], _pending["script"])
            reply = "Done. I " + _done["action"] + " the list script on " + _pending["doctype"] + ". Refresh the list to see it."
        except (frappe.ValidationError, frappe.PermissionError) as e:
            reply = str(e)
    elif re.match(r"\s*(no|nope|cancel|stop|never ?mind|don't|do not)\b", message, re.IGNORECASE):
        _draft = False
        record(context_docname, {"pending_list_script": None})
        reply = "Okay, I have not changed the list on " + _pending["doctype"] + "."
    else:
        message = (_pending.get("request") or "") + "\n\nChange to the draft: " + message
        doctype = _pending["doctype"]

if _draft:
    if not (doctype and frappe.db.exists("DocType", doctype)):
        doctype = ""
    _rows = []
    _current = ""
    if doctype:
        for _f in frappe.get_meta(doctype).fields:
            _rows.append(_f.fieldname + " | " + _f.fieldtype + " | " + (_f.label or ""))
        try:
            _current = get_list_view_script(doctype).get("script") or ""
        except frappe.PermissionError as e:
            reply = str(e)
    if not reply:
        prompt = "DocType: " + (doctype or "not selected") + "\nFields:\n" + "\n".join(_rows)
        prompt += "\n\nCurrent list script:\n" + (_current or "none") + "\n\nUser request: " + message
        _system = (_subs.get("list_script_writer") or {}).get("prompt") or ""
        raw = run_sync(get_llm_adapter_from_settings(_cfg).complete(system=_system, user=prompt)).text
        _data = extract_json(raw) or {}
        _target = _data.get("doctype") or doctype
        _script = (_data.get("script") or "").strip()
        if _data.get("question") or not _script:
            reply = _data.get("question") or "Which DocType's list should I change, and how?"
        elif not frappe.db.exists("DocType", _target):
            reply = "I could not find a DocType called " + str(_target) + ". Which list do you mean?"
        else:
            _problems = validate_list_view_script(_target, _script)
            if _problems:
                reply = "I could not use that script:\n- " + "\n- ".join(_problems)
            else:
                record(context_docname, {"pending_list_script": {"doctype": _target, "script": _script, "request": message}})
                reply = (_data.get("summary") or "Here is the change to the list.") + "\n\n"
                reply += "This replaces the list script on " + _target + ".\n\n" if _current else ""
                reply += "```js\n" + _script + "\n```\n\nShall I apply it to the " + _target + " list?"
                _options = ["Yes, apply it", "No, cancel"]

update_turn(
    context_docname,
    intent="LIST_VIEW_SCRIPT",
    output={
        "intent": "LIST_VIEW_SCRIPT",
        "response": reply,
        "doctype_ir": None,
        "diff": None,
        "options": _options,
        "suggested_name": None,
    },
    done=True,
)
result["response"] = reply
"""

SHAPE = (
	f'<bpmn:scriptTask id="write_list_script" name="write_list_script" spiffworkflow:serverScript="{WRITE_SCRIPT}"'
	f' spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="{WRITE_SCRIPT}">\n'
	"        <bpmn:documentation>Draft or update the list script of an existing DocType, ask the person to confirm "
	"it, then apply it. Call only when classify_intent returns next write_list_script.</bpmn:documentation>\n"
	f"        <bpmn:script>{WRITE_SCRIPT}</bpmn:script>\n"
	"      </bpmn:scriptTask>\n"
	"    "
)
SHAPE_DI = (
	'<bpmndi:BPMNShape id="write_list_script_di" bpmnElement="write_list_script">\n'
	'        <dc:Bounds x="1430" y="560" width="100" height="70" />\n'
	"      </bpmndi:BPMNShape>\n"
	"    "
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name or not frappe.db.get_value("Server Script", {"api_method": CLASSIFY_API}, "name"):
		return
	_set_config(name)
	_route_from_classifier()
	if not frappe.db.exists("Server Script", WRITE_SCRIPT):
		frappe.get_doc(
			{"doctype": "Server Script", "name": WRITE_SCRIPT, "script_type": "API", "script": WRITE_SCRIPT_BODY}
		).insert(ignore_permissions=True)
	_add_shape()


def _set_config(name):
	doc = frappe.get_doc("AI Agent Configuration", name)
	if SYSTEM_NEW not in (doc.system_prompt or ""):
		doc.system_prompt = (doc.system_prompt or "").replace(SYSTEM_OLD, SYSTEM_NEW, 1)
	for row in doc.sub_prompts:
		if row.sub_agent_id == "intent_classifier" and "LIST_VIEW_SCRIPT" not in (row.prompt_text or ""):
			row.prompt_text = (row.prompt_text or "").replace(INTENT_ANCHOR, INTENT_RULE + INTENT_ANCHOR, 1).replace(
				ENUM_OLD, ENUM_NEW, 1
			)
	if not any(row.sub_agent_id == SUB_AGENT_ID for row in doc.sub_prompts):
		doc.append(
			"sub_prompts",
			{
				"sub_agent_id": SUB_AGENT_ID,
				"sub_agent_name": "List Script Writer",
				"temperature": 0.2,
				"prompt_text": WRITER_PROMPT,
			},
		)
	doc.save(ignore_permissions=True)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def _route_from_classifier():
	for anchor, replacement in ((ACCEPT_OLD, ACCEPT_NEW), (ROUTE_OLD, ROUTE_NEW), (PENDING_OLD, PENDING_NEW)):
		_edit_script(CLASSIFY_API, anchor, replacement)


def _add_shape():
	"""Put write_list_script in the map's Tools sub-process, then recompile the map."""
	from one_bpmn.api.compilation import compile_process_model

	xml = frappe.db.get_value("BPMN Process Model", MAP, "bpmn_xml") or ""
	if not xml or 'id="write_list_script"' in xml:
		return
	if xml.count("</bpmn:adHocSubProcess>") != 1 or xml.count("</bpmndi:BPMNPlane>") != 1:
		frappe.log_error(
			title="docu_writes_list_view_scripts: map shape not added",
			message=f"{MAP} does not have exactly one ad-hoc sub-process and one diagram plane.",
		)
		return
	xml = xml.replace("</bpmn:adHocSubProcess>", SHAPE + "</bpmn:adHocSubProcess>")
	frappe.db.set_value("BPMN Process Model", MAP, "bpmn_xml", xml.replace("</bpmndi:BPMNPlane>", SHAPE_DI + "</bpmndi:BPMNPlane>"))
	compile_process_model(MAP)
