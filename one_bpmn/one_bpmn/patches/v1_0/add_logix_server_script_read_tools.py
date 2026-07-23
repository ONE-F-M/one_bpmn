# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Expose the remaining read-only Server Script tools to the Logix agent as shapes
in its ad-hoc "Tools" sub-process.

``add_logix_db_reference_tool`` already added ``reference_database`` (DocType /
field lookup). The other read helpers in
``one_bpmn/tools/tool_for_server_scripts.py`` were only reachable from inside
the writer stages (as ToolSpec ``fn``s). This patch surfaces them to the
orchestrating AI Agent Task as first-class tools it can call to ground a turn —
inspect an existing script before a MODIFY, or check whether a similar script
already exists — following the same "tools are the shapes" model.

Three new leaf tool shapes + backing Server Scripts:
- ``get_server_script``       — full Python source of a Server Script by name
- ``get_server_script_meta``  — a Server Script's configuration (no code)
- ``list_api_server_scripts`` — names of enabled API-type Server Scripts

Each Server Script is self-contained and FLAT (no def/lambda, no comprehension
over a module name) because the AI Agent shape-tool executor runs tool bodies
under split globals/locals (shape_tools._run_server_script). The lookups are
inlined (Frappe ORM only, no import) so the whole tool is visible and editable
in the Server Script on Processa — the same doctrine as reference_database and
the inlined pipeline stage tools.

Idempotent: Server Script bodies upsert (update-if-drifted); a shape is only
inserted into the model when its id is absent; the system prompt / tool-call
budget are re-applied every run (same result); the model is recompiled only
when the XML actually changed, so aiToolShapes re-embeds the new tools.
"""
import json
import re

import frappe

MODEL_NAME = "Logix – Script Task Agent"  # en-dash, matches the DB row


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Server Script bodies (FLAT, split-namespace safe, inlined ORM)
# ═══════════════════════════════════════════════════════════════════════════════

GET_SCRIPT_BODY = r'''# Logix – Tool Get Server Script (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# READ-ONLY: return the full Python source of an existing Server Script by its
# exact name so the agent can review it before proposing a MODIFY. The lookup is
# inlined (Frappe ORM only) so the whole tool is visible and editable here.
_args = task_data or {}
_name = (_args.get("script_name") or "").strip()
if not _name:
    result["error"] = "script_name is required."
elif not frappe.db.exists("Server Script", _name):
    result["error"] = "Server Script '" + _name + "' not found."
else:
    _doc = frappe.get_doc("Server Script", _name)
    result["content"] = _doc.script or ""
'''

GET_META_BODY = r'''# Logix – Tool Get Server Script Meta (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# READ-ONLY: return an existing Server Script's configuration (not its code) so
# the agent can see how it is wired. Inlined Frappe ORM — no module import.
_args = task_data or {}
_name = (_args.get("script_name") or "").strip()
if not _name:
    result["error"] = "script_name is required."
elif not frappe.db.exists("Server Script", _name):
    result["error"] = "Server Script '" + _name + "' not found."
else:
    _doc = frappe.get_doc("Server Script", _name)
    result["name"] = _doc.name
    result["script_type"] = _doc.script_type or ""
    result["reference_doctype"] = _doc.reference_doctype or ""
    result["doctype_event"] = _doc.doctype_event or ""
    result["api_method"] = _doc.api_method or ""
    result["disabled"] = bool(_doc.disabled)
'''

LIST_API_BODY = r'''# Logix – Tool List API Server Scripts (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda;
# a plain for-loop keeps names in the top-level scope (not a comprehension scope).
# READ-ONLY: list the names of all enabled API-type Server Scripts so the agent
# can check whether a similar script already exists. Inlined Frappe ORM.
_scripts = frappe.get_all(
    "Server Script",
    filters={"script_type": "API", "disabled": 0},
    fields=["name"],
    order_by="name asc",
    limit_page_length=100,
)
_names = []
for _s in _scripts:
    _names.append(_s.name)
result["scripts"] = _names
'''


# ═══════════════════════════════════════════════════════════════════════════════
# Tool specifications (shape + Server Script + LLM-facing schema + layout)
# ═══════════════════════════════════════════════════════════════════════════════

_SCRIPT_NAME_PARAM = {
    "properties": {
        "script_name": {
            "type": "string",
            "description": "Exact name (document ID) of the Server Script, e.g. 'Check Attendance'.",
        },
    },
    "required": ["script_name"],
}

TOOLS = [
    {
        "shape_id": "get_server_script",
        "script_name": "Logix – Tool Get Server Script",
        "api_method": "logix_tool_get_server_script",
        "documentation": (
            "Read-only. Return the full Python source of an existing Server Script by its "
            "exact name. Use it to review a script the user refers to before proposing "
            "changes. Never modifies anything."
        ),
        "params": _SCRIPT_NAME_PARAM,
        "body": GET_SCRIPT_BODY,
        "di": (1310, 460),
    },
    {
        "shape_id": "get_server_script_meta",
        "script_name": "Logix – Tool Get Server Script Meta",
        "api_method": "logix_tool_get_server_script_meta",
        "documentation": (
            "Read-only. Return an existing Server Script's configuration (script_type, "
            "reference_doctype, doctype_event, api_method, disabled) without its code."
        ),
        "params": _SCRIPT_NAME_PARAM,
        "body": GET_META_BODY,
        "di": (920, 570),
    },
    {
        "shape_id": "list_api_server_scripts",
        "script_name": "Logix – Tool List API Server Scripts",
        "api_method": "logix_tool_list_api_server_scripts",
        "documentation": (
            "Read-only. List the names of all enabled API-type Server Scripts, e.g. to "
            "check whether a script with a similar purpose already exists."
        ),
        "params": None,  # zero-argument tool
        "body": LIST_API_BODY,
        "di": (1050, 570),
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Model edits: shape, DI, system prompt, tool-call budget
# ═══════════════════════════════════════════════════════════════════════════════

_XML_TOOL_ANCHOR = "<bpmn:completionCondition"
_XML_DI_ANCHOR = "</bpmndi:BPMNPlane>"

# The Logix agent now offers four read-only reference tools; widen the tool-call
# budget so the agent can consult them and still finish the write/review/finalize
# pipeline within the cap.
_AI_MAX_TOOL_CALLS = "20"

_NEW_AI_SYSTEM_PROMPT = (
    "You run ONE turn of the Logix script-writing assistant by calling tools, one at a "
    "time. Step 1: call classify_intent; its result includes a 'next' field naming the "
    "tool to call next and a 'shape_kind' field describing the target element "
    "(script_task or agent_tool). Step 2: if next is clarify, call clarify then call "
    "finalize and stop. If next is write_script, call write_script then call "
    "review_script. If next is write_agent_tool, call write_agent_tool then call "
    "review_script. After review_script: if it returns approved true, call finalize and "
    "stop; if it returns approved false, call the SAME writer tool named by 'next' "
    "again, then review_script again, repeating at most 2 more times, then call "
    "finalize and stop. Always finish by calling finalize exactly once. You MAY also "
    "call the read-only reference tools at any point before a writer tool when you need "
    "to ground your work — reference_database (real DocType and field names), "
    "list_api_server_scripts (names of existing API scripts), and get_server_script / "
    "get_server_script_meta (an existing script's code and configuration); they do not "
    "advance the pipeline, so keep following the sequence above afterwards. Obey the "
    "'next' field, never skip a step, and never write code yourself."
)


def _tool_shape_xml(tool):
    params_attr = ""
    if tool["params"]:
        params_attr = ' spiffworkflow:aiToolParams="' + json.dumps(tool["params"]).replace('"', "&quot;") + '"'
    return (
        '<bpmn:scriptTask id="' + tool["shape_id"] + '" name="' + tool["shape_id"] + '" '
        'spiffworkflow:serverScript="' + tool["script_name"] + '" '
        'spiffworkflow:scriptType="Server Script" '
        'spiffworkflow:scriptName="' + tool["script_name"] + '"' + params_attr + '>\n'
        "        <bpmn:documentation>" + tool["documentation"] + "</bpmn:documentation>\n"
        "        <bpmn:script>" + tool["script_name"] + "</bpmn:script>\n"
        "      </bpmn:scriptTask>\n      "
    )


def _tool_di_xml(tool):
    x, y = tool["di"]
    return (
        '<bpmndi:BPMNShape id="' + tool["shape_id"] + '_di" bpmnElement="' + tool["shape_id"] + '">\n'
        '        <dc:Bounds x="' + str(x) + '" y="' + str(y) + '" width="100" height="70"/>\n'
        "      </bpmndi:BPMNShape>\n    "
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Patch steps
# ═══════════════════════════════════════════════════════════════════════════════

def _upsert_tool_scripts():
    """Create each tool's Server Script, or refresh its body if it has drifted."""
    for tool in TOOLS:
        name = tool["script_name"]
        if frappe.db.exists("Server Script", name):
            doc = frappe.get_doc("Server Script", name)
            if (doc.script or "").strip() != tool["body"].strip():
                doc.script = tool["body"]
                doc.save(ignore_permissions=True)
            continue
        frappe.get_doc({
            "doctype": "Server Script",
            "name": name,
            "script_type": "API",
            "api_method": tool["api_method"],
            "script": tool["body"],
            "disabled": 0,
        }).insert(ignore_permissions=True)


def _update_process_model():
    """Add any missing tool shapes + DI, refresh the routing prompt/budget, and
    recompile so aiToolShapes re-embeds the tools."""
    if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
        return
    xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
    original = xml

    if _XML_TOOL_ANCHOR not in xml or _XML_DI_ANCHOR not in xml:
        frappe.log_error(
            title="add_logix_server_script_read_tools: diagram anchors not found",
            message=f"'{MODEL_NAME}' bpmn_xml diverged from the expected layout; "
                    "add the read-tool shapes manually.",
        )
        return

    for tool in TOOLS:
        if f'id="{tool["shape_id"]}"' in xml:
            continue  # shape already present
        xml = xml.replace(_XML_TOOL_ANCHOR, _tool_shape_xml(tool) + _XML_TOOL_ANCHOR, 1)
        xml = xml.replace(_XML_DI_ANCHOR, _tool_di_xml(tool) + _XML_DI_ANCHOR, 1)

    # Grow the Tools sub-process container so the third row of shapes fits (DI is
    # cosmetic; robust to the current height value and idempotent).
    xml = re.sub(
        r'(id="logix_tools_di"[^>]*>\s*<dc:Bounds x="900" y="320" width="550" height=")\d+(")',
        r'\g<1>360\g<2>',
        xml,
        count=1,
    )

    # Re-apply the fuller routing prompt + widened tool-call budget (idempotent).
    xml = re.sub(
        r'spiffworkflow:aiSystemPrompt="[^"]*"',
        lambda _m: f'spiffworkflow:aiSystemPrompt="{_NEW_AI_SYSTEM_PROMPT}"',
        xml,
        count=1,
    )
    xml = re.sub(
        r'spiffworkflow:aiMaxToolCalls="[^"]*"',
        lambda _m: f'spiffworkflow:aiMaxToolCalls="{_AI_MAX_TOOL_CALLS}"',
        xml,
        count=1,
    )

    if xml == original:
        return  # nothing changed — no recompile needed

    # db_set avoids the editability gate (trusted content migration, same
    # rationale as compile_process_model's skip_editability_check).
    frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

    from one_bpmn.api.compilation import compile_process_model
    try:
        compile_process_model(MODEL_NAME)
    except Exception:
        frappe.log_error(
            title="add_logix_server_script_read_tools: recompile failed",
            message=frappe.get_traceback(),
        )


def execute():
    _upsert_tool_scripts()
    _update_process_model()
    frappe.db.commit()
