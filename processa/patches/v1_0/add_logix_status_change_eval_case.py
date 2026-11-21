"""Logix's baseline suite checks that a status change gets an Apply Workflow answer and no script."""

import json

import frappe

AGENT_ID = "logix_agent"
SHAPE = "run_logix_agent"
SUITE_TITLE = "Logix - Baseline"
TITLE = "A request to complete a document points to Apply Workflow and writes no script"
CONTEXT = {
	"element_name": "Complete Overtime Request",
	"process_context": {
		"element_id": "task_complete_overtime",
		"element_name": "Complete Overtime Request",
		"element_type": "ScriptTask",
		"process_name": "overtime_request_lifecycle",
		"parent_type": "Process",
		"shape_kind": "script_task",
		"incoming": [],
		"outgoing": [],
	},
}


def finalize_check(path: str, matcher: str, expected: str) -> dict:
	value = {"tool": "finalize", "path": path, "matcher": matcher, "expected": expected}
	return {"assertion_type": "tool_artifact", "value": json.dumps(value)}


def execute():
	process_model = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "process_model")
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite or not process_model or frappe.db.exists("AI Eval Case", {"suite": suite, "title": TITLE}):
		return
	frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"suite": suite,
			"title": TITLE,
			"case_type": "Trajectory",
			"process_model": process_model,
			"bpmn_id": SHAPE,
			"input_user_prompt": "Mark the overtime request as completed when the Finance Manager approves it.",
			"input_context": json.dumps(CONTEXT),
			"assertions": [
				{"assertion_type": "regex", "value": r"(?i)apply workflow"},
				{"assertion_type": "regex", "value": r"(?i)completed"},
				{"assertion_type": "no_tool_call", "value": "write_script, write_agent_tool"},
				finalize_check("modified_script", "equals", "null"),
			],
		}
	).insert(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
