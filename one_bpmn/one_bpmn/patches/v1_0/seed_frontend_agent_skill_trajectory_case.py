"""Frontend Agent Trajectory gains a case: frontend-house-style is loaded before a Vue file is edited.

A separate patch, since the suite's seed has already run on most sites. Like the rest of that
suite the case carries out a real work order, so run it deliberately.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_frontend_agent_trajectory_suite import (
	AGENT,
	MAP,
	SHAPE,
	_fixture_task,
	_suite,
)

TITLE = "load_skill frontend-house-style is called before a Vue file is edited"

PAYLOAD = {
	"instruction": (
		"On the Home view in spiff, change the page heading from 'Processes' to 'Your Processes'."
	),
	"work_item": "Reword the Home view heading",
	"target_app": "one_bpmn",
	"git_branch": "staging",
}

EXPECTED_CALLS = [
	{
		"call_order": 1,
		"tool_name": "load_skill",
		"argument": "skill_name",
		"matcher": "equals",
		"expected_value": "frontend-house-style",
	},
	{"call_order": 2, "tool_name": "edit_file"},
]


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT) or not frappe.db.exists(
		"BPMN Process Model", MAP
	):
		return

	suite = _suite()
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": TITLE}, "name")
	task = _fixture_task(existing, PAYLOAD)
	case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
	case.suite = suite
	case.title = TITLE
	case.case_type = "Trajectory"
	case.process_model = MAP
	case.bpmn_id = SHAPE
	case.input_user_prompt = PAYLOAD["instruction"]
	case.input_context = json.dumps({"context_doctype": "A2A Task", "context_docname": task})
	case.set("assertions", [{"assertion_type": "tool_calls", "value": "IN_ORDER"}])
	case.set("expected_tool_calls", EXPECTED_CALLS)
	if existing:
		case.save(ignore_permissions=True)
	else:
		case.insert(ignore_permissions=True)
