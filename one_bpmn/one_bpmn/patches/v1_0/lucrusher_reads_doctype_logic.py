# Copyright (c) 2026, one-fm and contributors
"""LuCrusher gets a tool that reads the controller, hooks, Server Scripts and Workflow of DocTypes.

Creates the tool's Server Script and splices its shape into the tools sub-process of the
LuCrusher map, then recompiles. Both steps leave an already patched site unchanged.
"""

import re

import frappe

from one_bpmn.one_bpmn.patches.v1_0.add_assistant_eval_authoring_tools import (
	_ensure_script,
	_shape_xml,
)

MODEL_NAME = "LuCrusher \u2013 Migration Agent"
ADHOC_ID = "lucrusher_tools"
SCRIPT_NAME = "LuCrusher - Tool Read DocType Logic"
API_METHOD = "lucrusher_tool_read_doctype_logic"
SHAPE_ID = "read_doctype_logic"
BOUNDS = (870, 460, 120, 70)
XML_TOOL_ANCHOR = "<bpmn:completionCondition"

SHAPE = {
	"id": SHAPE_ID,
	"name": SHAPE_ID,
	"script": SCRIPT_NAME,
	"params": {
		"properties": {
			"doctypes": {
				"type": "array",
				"items": {"type": "string"},
				"description": (
					"Exact DocType names, at most 5 per call (for example Event Staff). "
					"Take them from the codebase scan or the user. Call again for the rest."
				),
			}
		},
		"required": ["doctypes"],
	},
	"documentation": (
		"Read the server behaviour of up to 5 DocTypes: controller methods and module functions with "
		"trimmed bodies, doc_events, override and scheduler hooks that target it, Server Scripts on it, "
		"and its active Workflow (states, transitions, allowed roles). Call it for the DocTypes of the "
		"process being drafted, before drafting. A DocType with no code file is reported, not an error."
	),
}

READ_DOCTYPE_LOGIC_SCRIPT = '''# LuCrusher - Tool Read DocType Logic  (bpmn_id: read_doctype_logic)
# Reads controller, hook, Server Script and Workflow logic of up to 5 DocTypes. Self-contained
# (split globals/locals). File reads come from one_bpmn.agents.codebase_index, because the
# script gate forbids os and open().
def _lucrusher_read_doctype_logic(frappe, doctypes):
    import json

    from one_bpmn.agents.codebase_index import read_doctype_sources

    MAX_DOCTYPES = 5
    BODY_LINES = 60
    MAX_OUTPUT_CHARS = 30000
    SHRINK_STEPS = [(30, ["controller", "side"]), (15, ["controller", "side"]), (0, ["side"]), (0, ["controller"])]

    def _cut(text, limit):
        return "\\n".join((text or "").splitlines()[:limit])

    def _workflow(doctype):
        rows = frappe.get_all(
            "Workflow",
            filters={"document_type": doctype, "is_active": 1},
            fields=["name", "workflow_state_field"],
            limit_page_length=1,
        )
        if not rows:
            return None
        wf = frappe.get_doc("Workflow", rows[0]["name"])
        return {
            "name": wf.name,
            "state_field": wf.workflow_state_field,
            "states": [
                {"state": s.state, "doc_status": s.doc_status, "allow_edit": s.allow_edit} for s in wf.states
            ],
            "transitions": [
                {
                    "state": t.state,
                    "action": t.action,
                    "next_state": t.next_state,
                    "allowed": t.allowed,
                    "condition": t.condition,
                    "allow_self_approval": t.allow_self_approval,
                }
                for t in wf.transitions
            ],
        }

    def _server_scripts(doctype):
        try:
            rows = frappe.get_list(
                "Server Script",
                filters={"reference_doctype": doctype, "disabled": 0},
                fields=["name", "script_type", "doctype_event", "script"],
                limit_page_length=20,
            )
        except Exception as exc:
            return [], "could not read Server Scripts: " + str(exc)
        out = []
        for row in rows:
            lines = [l for l in (row["script"] or "").splitlines() if l.strip() and not l.strip().startswith("#")]
            out.append({
                "name": row["name"],
                "script_type": row["script_type"],
                "doctype_event": row["doctype_event"],
                "body": "\\n".join(lines[:BODY_LINES]),
            })
        return out, ""

    def _holders(doc, group):
        found = []
        if group == "controller":
            found += (doc.get("methods") or []) + (doc.get("module_functions") or [])
        else:
            for hook in doc.get("hooks") or []:
                found.append(hook)
                found += hook.get("methods") or []
            found += doc.get("server_scripts") or []
        return [h for h in found if "body" in h]

    def _size(payload):
        return len(json.dumps(payload, default=str))

    def _names_only(payload):
        for doc in payload["doctypes"]:
            for key in ("methods", "module_functions"):
                doc[key] = [{"name": f["name"], "line": f["line"]} for f in doc.get(key) or []]
            doc["hooks"] = [
                {k: h.get(k) for k in ("hook_type", "event", "method", "file", "line")} for h in doc.get("hooks") or []
            ]
            doc["server_scripts"] = [
                {k: s.get(k) for k in ("name", "script_type", "doctype_event")} for s in doc.get("server_scripts") or []
            ]

    def _fit(payload):
        for limit, groups in SHRINK_STEPS:
            if _size(payload) <= MAX_OUTPUT_CHARS:
                return payload
            for doc in payload["doctypes"]:
                for group in groups:
                    for holder in _holders(doc, group):
                        holder["body"] = _cut(holder["body"], limit)
                        holder["trimmed"] = True
            payload["truncated"] = True
            payload["truncation_note"] = "Bodies were cut to fit the size cap; names, lines and workflows are complete."
        if _size(payload) > MAX_OUTPUT_CHARS:
            _names_only(payload)
            payload["truncation_note"] = (
                "Bodies were dropped to fit the size cap; only names and lines are listed. "
                "Call again with fewer DocTypes to read bodies."
            )
            for limit in (60, 25, 10):
                if _size(payload) <= MAX_OUTPUT_CHARS:
                    break
                for doc in payload["doctypes"]:
                    for key in ("methods", "module_functions", "hooks", "server_scripts"):
                        total = len(doc.get(key) or [])
                        if total > limit:
                            doc[key] = doc[key][:limit]
                            doc[key + "_total"] = total
        return payload

    raw = doctypes or []
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            raw = decoded if isinstance(decoded, list) else [raw]
        except Exception:
            raw = [raw]
    names, seen = [], set()
    for entry in raw:
        text = str(entry).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            names.append(text)
    if not names:
        return {"error": "No DocType names supplied.", "doctypes": [], "read": [], "skipped": []}

    read_names, skipped = names[:MAX_DOCTYPES], names[MAX_DOCTYPES:]
    docs = read_doctype_sources(read_names, BODY_LINES)
    for doc in docs:
        doc["workflow"] = _workflow(doc["doctype"])
        doc["server_scripts"], note = _server_scripts(doc["doctype"])
        if note:
            doc["server_scripts_note"] = note

    payload = {
        "doctypes": docs,
        "read": read_names,
        "skipped": skipped,
        "truncated": False,
        "note": ("Only the first " + str(MAX_DOCTYPES) + " DocTypes were read; call again for the skipped ones.") if skipped else "",
    }
    return _fit(payload)


result["doctype_logic"] = _lucrusher_read_doctype_logic(frappe, task_data.get("doctypes") or [])
'''


def _splice_shape(xml: str) -> str:
	"""The map XML with the tool shape and its diagram bounds added, or the input when not possible."""
	adhoc = re.search(rf'<bpmn:adHocSubProcess id="{ADHOC_ID}".*?</bpmn:adHocSubProcess>', xml, re.S)
	if not adhoc or XML_TOOL_ANCHOR not in adhoc.group(0) or "</bpmndi:BPMNPlane>" not in xml:
		return xml
	patched_adhoc = adhoc.group(0).replace(XML_TOOL_ANCHOR, _shape_xml(SHAPE) + XML_TOOL_ANCHOR, 1)
	xml = xml[: adhoc.start()] + patched_adhoc + xml[adhoc.end() :]
	x, y, width, height = BOUNDS
	di = (
		f'\n      <bpmndi:BPMNShape id="{SHAPE_ID}_di" bpmnElement="{SHAPE_ID}">\n'
		f'        <dc:Bounds x="{x}" y="{y}" width="{width}" height="{height}" />\n'
		f"      </bpmndi:BPMNShape>\n      "
	)
	plane_close = xml.rfind("</bpmndi:BPMNPlane>")
	return xml[:plane_close] + di + xml[plane_close:]


def _update_process_model() -> None:
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if f'id="{SHAPE_ID}"' in xml:
		return
	patched = _splice_shape(xml)
	if patched == xml:
		frappe.log_error(
			title="lucrusher_reads_doctype_logic: tools sub-process anchor not found",
			message=f"'{MODEL_NAME}' has no '{ADHOC_ID}' sub-process with a completionCondition or no diagram plane; "
			f"add the {SHAPE_ID} shape by hand.",
		)
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", patched)
	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(MODEL_NAME)


def execute():
	_ensure_script(SCRIPT_NAME, API_METHOD, READ_DOCTYPE_LOGIC_SCRIPT)
	_update_process_model()
