# Copyright (c) 2026, one-fm and contributors
"""Logix reads the controller logic of a DocType before it writes a script for it.

Adds a read_doctype_logic tool to the Logix map, shows what it read to the script writer,
and tells the agent and the writers to follow the methods that already exist.
"""

import json

import frappe

from processa.patches.v1_0.add_assistant_eval_authoring_tools import _ensure_script, _shape_xml
from processa.patches.v1_0.approve_live_script_tasks import approve

MODEL_NAME = "Logix \u2013 Script Task Agent"
SCRIPT_NAME = "Logix \u2013 Tool Read DocType Logic"
API_METHOD = "logix_tool_read_doctype_logic"
SHAPE_ID = "read_doctype_logic"
TOOL_ANCHOR = '<bpmn:serviceTask id="write_script"'
WRITER_PROMPT_ANCHOR = "{% if turn.violations %}"
WRITER_PROMPT_BLOCK = (
	"{% if turn.doctype_logic %}**Server logic of the DocType (its controller methods and hooks):**&#10;"
	"{{ turn.doctype_logic | tojson }}&#10;&#10;{% endif %}"
)
DI = (
	f'\n      <bpmndi:BPMNShape id="{SHAPE_ID}_di" bpmnElement="{SHAPE_ID}">\n'
	'        <dc:Bounds x="1310" y="570" width="100" height="70" />\n'
	"      </bpmndi:BPMNShape>\n      "
)

SHAPE = {
	"id": SHAPE_ID,
	"name": SHAPE_ID,
	"script": SCRIPT_NAME,
	"params": {
		"properties": {
			"doctypes": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Exact DocType names the script works on, at most 3 (for example Overtime Request).",
			}
		},
		"required": ["doctypes"],
	},
	"documentation": (
		"Read the controller methods and hooks of the DocTypes a script works on, and pass them to "
		"write_script. Call it before write_script when the request is about a DocType's records."
	),
}

SCRIPT = """# Logix - Tool Read DocType Logic (bpmn_id: read_doctype_logic)
# Reads the controller methods and hooks of up to 3 DocTypes and keeps them for write_script.
from processa.ai_agent_registry.definitions.lucrusher.tools import read_doctype_sources
from processa.processa_engine.agent_runtime.turn_state import update_turn

_names = [str(n).strip() for n in (task_data.get("doctypes") or []) if str(n).strip()][:3]
_logic = read_doctype_sources(_names, 40)
update_turn(context_docname, doctype_logic=_logic)
result["doctype_logic"] = _logic
"""

AGENT = (
	"DocType logic: when next is write_script and the request is about a DocType's records, call "
	"read_doctype_logic with that DocType first, then write_script."
)
WRITER = (
	"Existing DocType logic: when the request carries a Server logic block, read it before writing. If a "
	"controller method already holds the rule asked for, the script replaces it: copy that method's conditions, "
	"thresholds and error messages exactly, and name the method it replaces in your reply (this one name is "
	"allowed). If the request contradicts that method (a different limit, window or trigger), write no code: "
	"list the difference and ask which one is right. If no method covers it, say in one sentence that the rule "
	"is new and not in the code today. An empty block or a status of no_controller_file means there is no "
	"code to follow."
)
GUIDANCE = {
	"logix_agent": AGENT,
	"logix_script_writer": WRITER,
	"logix_tool_writer": WRITER,
}

SUITE_TITLE = "Logix - Baseline"
CASE_TITLE = "A rule the DocType's controller already enforces is reused, not written again"
CASE_PROMPT = "Stop the Overtime Request when its Compensatory Day Off date is more than 7 days after the overtime date."
CASE_CONTEXT = {
	"element_name": "Check Day Off Window",
	"process_context": {
		"element_id": "task_check_day_off_window",
		"element_name": "Check Day Off Window",
		"element_type": "ScriptTask",
		"process_name": "overtime_request",
		"parent_type": "Process",
		"shape_kind": "script_task",
		"incoming": [],
		"outgoing": [],
	},
}


def execute():
	_ensure_script(SCRIPT_NAME, API_METHOD, SCRIPT)
	# The map only compiles once the new tool's imports are approved.
	_approve_imports()
	_update_process_model()
	_add_guidance()
	_add_eval_case()


def _update_process_model():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	patched = _splice(xml)
	if patched == xml:
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", patched)
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def _splice(xml):
	"""The map with the tool shape, its bounds and the writer's logic block added, or the input when done or not possible."""
	if not xml or f'id="{SHAPE_ID}"' in xml:
		return xml
	start = xml.find(TOOL_ANCHOR)
	anchor = xml.find(WRITER_PROMPT_ANCHOR, start)
	if (
		start < 0
		or anchor < 0
		or anchor > xml.find("</bpmn:serviceTask>", start)
		or "</bpmndi:BPMNPlane>" not in xml
	):
		frappe.log_error(
			title="logix_reads_doctype_logic: anchor not found",
			message=f"'{MODEL_NAME}' has no write_script shape or no violations block; add {SHAPE_ID} by hand.",
		)
		return xml
	xml = xml[:start] + _shape_xml(SHAPE) + xml[start:anchor] + WRITER_PROMPT_BLOCK + xml[anchor:]
	plane_close = xml.rfind("</bpmndi:BPMNPlane>")
	return xml[:plane_close] + DI + xml[plane_close:]


def _approve_imports():
	process = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "process_name")
	if process and not frappe.db.exists(
		"Script Approval Request",
		{
			"process_name": process,
			"script_task": SHAPE_ID,
			"server_script": SCRIPT_NAME,
			"status": "Approved",
		},
	):
		approve(process, SHAPE_ID, SHAPE_ID, SCRIPT_NAME)


def _add_guidance():
	for agent_id, guidance in GUIDANCE.items():
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		if not name:
			continue
		config = frappe.get_doc("AI Agent Configuration", name)
		if guidance in (config.system_prompt or ""):
			continue
		config.system_prompt = ((config.system_prompt or "").rstrip() + "\n\n" + guidance).strip()
		config.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def _add_eval_case():
	process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": "logix_agent"}, "process_model"
	)
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if (
		not suite
		or not process_model
		or frappe.db.exists("AI Eval Case", {"suite": suite, "title": CASE_TITLE})
	):
		return
	frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"suite": suite,
			"title": CASE_TITLE,
			"case_type": "Trajectory",
			"process_model": process_model,
			"bpmn_id": "run_logix_agent",
			"input_user_prompt": CASE_PROMPT,
			"input_context": json.dumps(CASE_CONTEXT),
			"assertions": [
				{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
				{"assertion_type": "regex", "value": "validate_compensatory_day_off"},
				_finalize_check(r"add_days\([^)]*7\)"),
				_finalize_check("within 7 days of the overtime"),
			],
			"expected_tool_calls": [{"call_order": 1, "tool_name": "read_doctype_logic"}],
		}
	).insert(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def _finalize_check(expected):
	value = {"tool": "finalize", "path": "modified_script", "matcher": "regex", "expected": expected}
	return {"assertion_type": "tool_artifact", "value": json.dumps(value)}
