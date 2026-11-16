"""Seeds one Baseline case: a "paginate by 5" request yields limit_start and limit_page_length, never a loop.

Idempotent by suite and case title; a site without Logix is left alone.
"""

import json

import frappe

from processa.patches.v1_0.seed_logix_baseline_suite import (
	AGENT_ID,
	ANSWERED_AT_ALL,
	IN_ORDER,
	IT_EMPLOYEES_SHAPE,
	SHAPE,
	SUITE_TITLE,
)

TITLE = "Paginate by five reads limit_start and limit_page_length from task data"
PROMPT = "paginate by 5"


def final_output(path, matcher, expected):
	return {
		"assertion_type": "tool_artifact",
		"value": json.dumps({"tool": "finalize", "path": path, "matcher": matcher, "expected": expected}),
	}


ASSERTIONS = [
	final_output("intent", "equals", "MODIFY"),
	final_output("modified_script", "regex", r"limit_page_length"),
	final_output("modified_script", "regex", r"limit_start"),
	final_output("modified_script", "regex", r"task_data"),
	final_output("modified_script", "regex", r"^(?![\s\S]*\bwhile\b)"),
	final_output("modified_script", "regex", r"^(?![\s\S]*\bimport\b)"),
]
CALLS = [
	{"call_order": i, "tool_name": tool, "argument": "", "matcher": "", "expected_value": ""}
	for i, tool in enumerate(("classify_intent", "write_script", "review_script", "finalize"), start=1)
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return
	suite = frappe.db.get_value("AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}, "name")
	if not suite:
		return
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": TITLE}, "name")
	case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
	case.suite = suite
	case.title = TITLE
	case.case_type = "Trajectory"
	case.process_model = process_model
	case.bpmn_id = SHAPE
	case.input_user_prompt = PROMPT
	case.input_context = json.dumps(IT_EMPLOYEES_SHAPE)
	case.set("assertions", [ANSWERED_AT_ALL, IN_ORDER, *ASSERTIONS])
	case.set("expected_tool_calls", CALLS)
	if existing:
		case.save(ignore_permissions=True)  # patch: seeded eval case
	else:
		case.insert(ignore_permissions=True)  # patch: seeded eval case
