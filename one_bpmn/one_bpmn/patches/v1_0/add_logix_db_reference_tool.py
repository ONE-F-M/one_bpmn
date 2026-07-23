# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Give Logix a read-only database reference tool.

Logix could already read an individual DocType's fields from *inside* the
writer stage (the ``get_doctype_fields`` ToolSpec), but the orchestrating AI
Agent Task had no way to reference real DocType/field names while reasoning
about a turn, and nothing anywhere could discover which DocType *names* exist.

This patch adds a new leaf tool shape — ``reference_database`` — to the Logix
agent's ad-hoc "Tools" sub-process (the "tools are the shapes" model: every
executable leaf shape of the sub-process is compiled into a callable tool the
agent invokes as a function). Given a ``doctype`` it returns that DocType's
fields; otherwise it lists DocType names (optionally filtered by ``search``).
It is strictly read-only.

Three idempotent DB changes (guarded on the ``reference_database`` marker so
re-running, or running against a manually edited row, is a no-op):

1. **"Logix – Tool Reference Database" Server Script** — a self-contained FLAT
   stage tool (no def/lambda: it runs under the AI Agent shape-tool executor's
   split globals/locals, see shape_tools._run_server_script) that imports the
   shared read helpers and writes its result onto ``result``.
2. **"Logix – Script Task Agent" process model** — the ``reference_database``
   shape (with a ``spiffworkflow:aiToolParams`` JSON Schema declaring its
   optional ``doctype``/``search`` arguments) added to the ad-hoc Tools
   sub-process, plus a matching DI shape, and the AI Agent Task's system prompt
   updated so the agent knows it MAY call the tool.
3. The model is recompiled so the embedded ``aiToolShapes`` include the new
   tool (new conversations pick it up; running instances keep their old spec).
"""
import json
import re

import frappe

MODEL_NAME = "Logix – Script Task Agent"  # en-dash, matches the DB row
REFERENCE_TOOL_SCRIPT_NAME = "Logix – Tool Reference Database"
_MARKER = "reference_database"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. The stage-tool Server Script (FLAT, split-namespace safe)
# ═══════════════════════════════════════════════════════════════════════════════

REFERENCE_TOOL_SCRIPT = r'''# Logix – Tool Reference Database (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — so it uses NO
# def/lambda and no comprehension referencing a module-level import/const.
# READ-ONLY schema reference so the agent can ground scripts in real DocTypes and
# fields. Given a `doctype`, returns that DocType's fields; otherwise lists
# DocType names (optionally filtered by `search`). Never writes to the database.
import json
from one_bpmn.tools.tool_for_server_scripts import get_doctype_fields, list_doctypes

# The shape-tool executor injects the LLM's arguments both as bare locals and,
# bundled, as `task_data`. Read them through task_data so an omitted optional
# argument is a missing key (not a NameError).
_args = task_data or {}
_doctype = (_args.get("doctype") or "").strip()
_search = (_args.get("search") or "").strip()

if _doctype:
    _raw = get_doctype_fields(_doctype)
    try:
        _parsed = json.loads(_raw)
    except (json.JSONDecodeError, TypeError):
        _parsed = _raw
    result["doctype"] = _doctype
    if isinstance(_parsed, dict) and _parsed.get("error"):
        result["error"] = _parsed["error"]
    else:
        result["fields"] = _parsed
else:
    _raw = list_doctypes(_search)
    try:
        _parsed = json.loads(_raw)
    except (json.JSONDecodeError, TypeError):
        _parsed = []
    result["search"] = _search
    result["doctypes"] = _parsed
'''


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Process model: new reference_database shape + aiToolParams + routing prompt
# ═══════════════════════════════════════════════════════════════════════════════

# Optional arguments the LLM may pass. `_extract_tool_shapes` reads this JSON
# from the spiffworkflow:aiToolParams attribute; with a non-empty `properties`
# the tool is exposed with a real argument schema instead of as zero-arg.
_TOOL_PARAMS = {
    "properties": {
        "doctype": {
            "type": "string",
            "description": (
                "Exact DocType name to inspect, e.g. 'Employee'. When provided, "
                "returns that DocType's fields (fieldname, fieldtype, label, reqd). "
                "Omit to list DocType names instead."
            ),
        },
        "search": {
            "type": "string",
            "description": (
                "Substring to filter DocType names by when listing them (used only "
                "when 'doctype' is omitted), e.g. 'leave'."
            ),
        },
    },
    "required": [],
}
_TOOL_PARAMS_ATTR = json.dumps(_TOOL_PARAMS).replace('"', "&quot;")

# Semantic shape — inserted before the ad-hoc sub-process's completionCondition.
_XML_TOOL_ANCHOR = "<bpmn:completionCondition"

_XML_TOOL_SHAPE = (
    '<bpmn:scriptTask id="reference_database" name="reference_database" '
    'spiffworkflow:serverScript="Logix – Tool Reference Database" '
    'spiffworkflow:scriptType="Server Script" '
    'spiffworkflow:scriptName="Logix – Tool Reference Database" '
    'spiffworkflow:aiToolParams="' + _TOOL_PARAMS_ATTR + '">\n'
    "        <bpmn:documentation>Read-only database reference. Look up real DocType "
    "and field names so scripts reference them correctly. Pass a `doctype` to get "
    "that DocType's fields (fieldname, fieldtype, label, reqd); omit it (optionally "
    "with `search`) to list matching DocType names. Never changes data. Call it "
    "whenever you are unsure a DocType or field name exists.</bpmn:documentation>\n"
    "        <bpmn:script>Logix – Tool Reference Database</bpmn:script>\n"
    "      </bpmn:scriptTask>\n      "
)

# DI shape — inserted just before the plane closes (DI order is irrelevant to
# parsing; anchoring on the plane close is robust to editor reformatting).
_XML_DI_ANCHOR = "</bpmndi:BPMNPlane>"

_XML_DI_SHAPE = (
    '<bpmndi:BPMNShape id="reference_database_di" bpmnElement="reference_database">\n'
    '        <dc:Bounds x="1180" y="460" width="100" height="70"/>\n'
    "      </bpmndi:BPMNShape>\n    "
)

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
    "call reference_database at any point before a writer tool to look up real DocType "
    "names and field names (read-only) when you are unsure they exist — it does not "
    "advance the pipeline, so keep following the sequence above afterwards. Obey the "
    "'next' field, never skip a step, and never write code yourself."
)


# ═══════════════════════════════════════════════════════════════════════════════
# Patch steps
# ═══════════════════════════════════════════════════════════════════════════════

def _create_reference_tool_script():
    """Create the read-only reference stage tool Server Script (skip if present)."""
    if frappe.db.exists("Server Script", REFERENCE_TOOL_SCRIPT_NAME):
        return
    frappe.get_doc({
        "doctype": "Server Script",
        "name": REFERENCE_TOOL_SCRIPT_NAME,
        "script_type": "API",
        "api_method": "logix_tool_reference_database",
        "script": REFERENCE_TOOL_SCRIPT,
        "disabled": 0,
    }).insert(ignore_permissions=True)


def _update_process_model():
    """Add the reference_database shape + routing prompt, then recompile."""
    if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
        return
    xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
    if _MARKER in xml:
        return  # already patched

    if _XML_TOOL_ANCHOR not in xml or _XML_DI_ANCHOR not in xml:
        frappe.log_error(
            title="add_logix_db_reference_tool: diagram anchors not found",
            message=f"'{MODEL_NAME}' bpmn_xml diverged from the expected layout; "
                    "add the reference_database shape manually.",
        )
        return

    xml = xml.replace(_XML_TOOL_ANCHOR, _XML_TOOL_SHAPE + _XML_TOOL_ANCHOR, 1)
    xml = xml.replace(_XML_DI_ANCHOR, _XML_DI_SHAPE + _XML_DI_ANCHOR, 1)
    xml = re.sub(
        r'spiffworkflow:aiSystemPrompt="[^"]*"',
        lambda _m: f'spiffworkflow:aiSystemPrompt="{_NEW_AI_SYSTEM_PROMPT}"',
        xml,
        count=1,
    )

    # db_set avoids the editability gate (this is a trusted content migration,
    # same rationale as compile_process_model's skip_editability_check).
    frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

    # Recompile so serialized_spec embeds the new tool in aiToolShapes.
    from one_bpmn.api.compilation import compile_process_model
    try:
        compile_process_model(MODEL_NAME)
    except Exception:
        frappe.log_error(
            title="add_logix_db_reference_tool: recompile failed",
            message=frappe.get_traceback(),
        )


def execute():
    _create_reference_tool_script()
    _update_process_model()
    frappe.db.commit()
