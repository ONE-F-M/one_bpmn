"""Logix's baseline suite checks that a request a library on the map covers calls it through import_script."""

import json

import frappe

AGENT_ID = "logix_agent"
SHAPE = "run_logix_agent"
SUITE_TITLE = "Logix - Baseline"
LIBRARY = "P: Lib Replies"
TITLE = "A request a library on the map covers calls the library through import_script"
CONTEXT = {
	"element_name": "Clean Reply",
	"library_scripts": [{"name": LIBRARY, "functions": ["strip_fences(text)"]}],
	"process_context": {
		"element_id": "task_clean_reply",
		"element_name": "Clean Reply",
		"element_type": "ScriptTask",
		"process_name": "prosally_1",
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
			"input_user_prompt": "Strip the code fences from the model reply in task_data['reply'] and put it in result['clean'].",
			"input_context": json.dumps(CONTEXT),
			"assertions": [
				{"assertion_type": "regex", "value": r"\S"},
				finalize_check(
					"modified_script", "regex", r"import_script\(\s*[\"']P: Lib Replies[\"']\s*\)"
				),
				finalize_check("modified_script", "regex", r"\.strip_fences\("),
			],
		}
	).insert(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
