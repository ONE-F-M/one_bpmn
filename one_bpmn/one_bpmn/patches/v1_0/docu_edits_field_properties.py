"""Docu applies a show/hide, mandatory or read-only request straight to the named field.

The classifier gains EDIT_FIELD_PROPERTY and routes it to a new edit_field_property stage, which asks
the field_property_editor sub-prompt for the change, writes it through apply_field_properties and replies
with what changed. Idempotent: every edit checks for its own result first.
"""

import frappe

AGENT_ID = "docu_agent"
MAP = "Docu – DocType Agent"
CLASSIFY = "Docu – Tool Classify Intent"
EDIT_SCRIPT = "Docu – Tool Edit Field Property"
SUB_AGENT_ID = "field_property_editor"

INTENT_ANCHOR = "\n- DISAMBIGUATE "
INTENT_RULE = (
	"\n- EDIT_FIELD_PROPERTY: the user only wants an existing field or section shown or hidden "
	"depending on another field, hidden, made mandatory or optional, or made read-only "
	'("hide the Coverage section unless the checkbox is ticked", "make Remarks mandatory"). '
	"A field the user names is enough: use it even when no form is selected, and never answer it "
	"with a question about what form to design."
)
ENUM_OLD = '"CREATE|MODIFY|DISAMBIGUATE|'
ENUM_NEW = '"CREATE|MODIFY|EDIT_FIELD_PROPERTY|DISAMBIGUATE|'

ACCEPT_OLD = 'if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE") and intent not in _cheap_intents:'
ACCEPT_NEW = 'if intent not in ("CREATE", "MODIFY", "EDIT_FIELD_PROPERTY", "DISAMBIGUATE") and intent not in _cheap_intents:'
ROUTE_OLD = 'nxt = "clarify" if intent == "DISAMBIGUATE" else "write_schema"'
ROUTE_NEW = 'nxt = {"DISAMBIGUATE": "clarify", "EDIT_FIELD_PROPERTY": "edit_field_property"}.get(intent, "write_schema")'

SYSTEM_OLD = "(3) If next is clarify: call clarify, then finalize, then stop."
SYSTEM_NEW = (
	"(3) If next is clarify: call clarify, then finalize, then stop. If next is edit_field_property: "
	"call edit_field_property, then finalize, then stop."
)

EDITOR_PROMPT = """You turn one request about an existing Frappe form into field property changes.
You are given the form's fields as "fieldname | type | label" and the user's request.

Allowed properties:
- depends_on: show the field only when a condition holds, as "eval:doc.<fieldname>" for a ticked checkbox or "eval:doc.<fieldname>=='<value>'" for a select. An empty string always shows it.
- hidden: 1 hides the field, 0 shows it.
- reqd: 1 makes it mandatory, 0 optional.
- read_only: 1 locks it, 0 makes it editable.

Use only fieldnames from the list. A section is its Section Break row; match it by label. "Hidden unless X is ticked" is depends_on, never hidden.

Respond with ONLY a JSON object:
{"changes": [{"fieldname": "...", "property": "depends_on|hidden|reqd|read_only", "value": "..."}]}
Return {"changes": []} when the request names no field you can find."""

EDIT_SCRIPT_BODY = """# Docu - Tool Edit Field Property (self-contained, FLAT top-level code; no def/lambda under the shape-tool exec).
# Sets depends_on, hidden, reqd or read_only on the fields the user names and replies with what changed.
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.prosally_helpers import extract_json
from one_bpmn.api.docu_api import apply_field_properties
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
message = turn.get("user_text", "")
doctype = turn.get("doctype", "")

# With no form selected, a stored fieldname that only one DocType has names the form.
if not (doctype and frappe.db.exists("DocType", doctype)):
    doctype = ""
    for _name in re.findall(r"\\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\\b", message):
        _parents = set(frappe.get_all("DocField", filters={"fieldname": _name, "parenttype": "DocType"}, pluck="parent"))
        _parents.update(frappe.get_all("Custom Field", filters={"fieldname": _name}, pluck="dt"))
        if len(_parents) == 1:
            doctype = _parents.pop()
            break

if not doctype:
    reply = "Which form is this on? Select it on the step, or give the field's stored name, and I'll make the change."
else:
    _rows = []
    for _f in frappe.get_meta(doctype).fields:
        _rows.append(_f.fieldname + " | " + _f.fieldtype + " | " + (_f.label or ""))
    prompt = "Form: " + doctype + "\\nFields:\\n" + "\\n".join(_rows) + "\\n\\nUser request: " + message
    _system = (_subs.get("field_property_editor") or {}).get("prompt") or ""
    raw = run_sync(get_llm_adapter_from_settings(_cfg).complete(system=_system, user=prompt)).text
    _data = extract_json(raw) or {}
    try:
        reply = "Done. On " + doctype + ":\\n- " + "\\n- ".join(apply_field_properties(doctype, _data.get("changes") or []))
    except (frappe.ValidationError, frappe.PermissionError) as e:
        reply = str(e)

update_turn(
    context_docname,
    intent="EDIT_FIELD_PROPERTY",
    output={
        "intent": "EDIT_FIELD_PROPERTY",
        "response": reply,
        "doctype_ir": None,
        "diff": None,
        "options": None,
        "suggested_name": None,
    },
    done=True,
)
result["response"] = reply
"""

SHAPE = (
	f'<bpmn:scriptTask id="edit_field_property" name="edit_field_property" spiffworkflow:serverScript="{EDIT_SCRIPT}"'
	f' spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="{EDIT_SCRIPT}">\n'
	"        <bpmn:documentation>Show or hide, require or lock fields the user names on an existing form, and reply "
	"with what changed. Call only when classify_intent returns next edit_field_property.</bpmn:documentation>\n"
	f"        <bpmn:script>{EDIT_SCRIPT}</bpmn:script>\n"
	"      </bpmn:scriptTask>\n"
	"    "
)
SHAPE_DI = (
	'<bpmndi:BPMNShape id="edit_field_property_di" bpmnElement="edit_field_property">\n'
	'        <dc:Bounds x="1310" y="560" width="100" height="70" />\n'
	"      </bpmndi:BPMNShape>\n"
	"    "
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name or not frappe.db.exists("Server Script", CLASSIFY):
		return
	_set_config(name)
	_route_from_classifier()
	if not frappe.db.exists("Server Script", EDIT_SCRIPT):
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": EDIT_SCRIPT,
				"script_type": "API",
				"script": EDIT_SCRIPT_BODY,
			}
		).insert(ignore_permissions=True)
	_add_shape()


def _set_config(name):
	doc = frappe.get_doc("AI Agent Configuration", name)
	if SYSTEM_NEW not in (doc.system_prompt or ""):
		doc.system_prompt = (doc.system_prompt or "").replace(SYSTEM_OLD, SYSTEM_NEW, 1)
	for row in doc.sub_prompts:
		text = row.prompt_text or ""
		if row.sub_agent_id == "intent_classifier" and "EDIT_FIELD_PROPERTY" not in text:
			row.prompt_text = text.replace(INTENT_ANCHOR, INTENT_RULE + INTENT_ANCHOR, 1).replace(
				ENUM_OLD, ENUM_NEW, 1
			)
	if not any(row.sub_agent_id == SUB_AGENT_ID for row in doc.sub_prompts):
		doc.append(
			"sub_prompts",
			{
				"sub_agent_id": SUB_AGENT_ID,
				"sub_agent_name": "Field Property Editor",
				"temperature": 0.0,
				"prompt_text": EDITOR_PROMPT,
			},
		)
	doc.save(ignore_permissions=True)


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


def _add_shape():
	"""Put edit_field_property in the free slot of the map's Tools sub-process, then recompile the map."""
	from one_bpmn.api.compilation import compile_process_model

	if not frappe.db.exists("BPMN Process Model", MAP):
		return
	model = frappe.get_doc("BPMN Process Model", MAP)
	xml = model.bpmn_xml or ""
	if 'id="edit_field_property"' in xml:
		return
	if xml.count("</bpmn:adHocSubProcess>") != 1 or xml.count("</bpmndi:BPMNPlane>") != 1:
		frappe.log_error(
			title="docu_edits_field_properties: map shape not added",
			message=f"{MAP} does not have exactly one ad-hoc sub-process and one diagram plane.",
		)
		return
	xml = xml.replace("</bpmn:adHocSubProcess>", SHAPE + "</bpmn:adHocSubProcess>")
	model.bpmn_xml = xml.replace("</bpmndi:BPMNPlane>", SHAPE_DI + "</bpmndi:BPMNPlane>")
	model.save(ignore_permissions=True)
	compile_process_model(MAP)
