"""Seeds Baseline cases: ordinary messages that must not be refused, a revert, and scripts that must run and follow the request.

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
from processa.patches.v1_0.seed_lucrusher_eval_suite import judge_for


def final_output(path, matcher, expected):
	return {
		"assertion_type": "tool_artifact",
		"value": json.dumps({"tool": "finalize", "path": path, "matcher": matcher, "expected": expected}),
	}


def script_task(element_id, name, process):
	return {
		"element_id": element_id,
		"element_name": name,
		"element_type": "ScriptTask",
		"process_name": process,
		"parent_type": "Process",
		"shape_kind": "script_task",
		"incoming": [],
		"outgoing": [],
	}


def call(order, tool):
	return {"call_order": order, "tool_name": tool, "argument": "", "matcher": "", "expected_value": ""}


NOT_REFUSED = final_output("response", "regex", r"^(?![\s\S]*unable to generate a safe script)")
CLASSIFY_THEN_FINALIZE = [call(1, "classify_intent"), call(2, "finalize")]

ABSENCE_SCRIPT = (
	"def execute_populate_21_days(target_doc=None):\n"
	"    today_obj = frappe.utils.getdate(frappe.utils.today())\n"
	"    current_year = today_obj.year\n"
	'    year_start = str(current_year) + "-01-01"\n'
	'    year_end = str(current_year) + "-12-31"\n'
	'    if target_doc and target_doc.get("employee"):\n'
	'        employees = [target_doc.get("employee")]\n'
	"    else:\n"
	'        employees = frappe.db.get_all("Employee", filters={"status": "Active"}, pluck="name")\n'
	"    created_cases = []\n"
	"    for emp_id in employees:\n"
	"        previous_cases = frappe.db.get_all(\n"
	'            "Absence Case",\n'
	'            filters={"employee": emp_id, "absence_type": "21 Days Absence in a Year", "docstatus": ["in", [0, 1]]},\n'
	'            fields=["absence_start_date", "absent_dates", "creation"],\n'
	'            order_by="creation desc",\n'
	"            limit=1,\n"
	"        )\n"
	"        if previous_cases:\n"
	"            continue\n"
	'        case = frappe.get_doc({"doctype": "Absence Case", "employee": emp_id, "absence_type": "21 Days Absence in a Year", "absence_start_date": year_start})\n'
	"        case.insert()\n"
	"        created_cases.append(case.name)\n"
	"    return created_cases"
)

BARE_SHAPE = {
	"element_name": "Generate Invoice",
	"process_context": script_task("task_generate_invoice", "Generate Invoice", "subcontract_attendance"),
}

WRITE_TRACE = [
	call(1, "classify_intent"),
	call(2, "write_script"),
	call(3, "review_script"),
	call(4, "finalize"),
]
PAYLOAD_SHAPE = {
	"element_name": "Count Payload Items",
	"process_context": script_task("task_count_items", "Count Payload Items", "payload_intake"),
}
TODO_SHAPE = {
	"element_name": "Collect Open ToDos",
	"process_context": script_task("task_collect_todos", "Collect Open ToDos", "todo_follow_up"),
}

CASES = [
	{
		"title": "A script that reads JSON imports what it uses before it is returned",
		"prompt": (
			"The step receives a JSON text in task_data under payload_json. Parse it and put the "
			"number of items it holds in result as item_count."
		),
		"context": PAYLOAD_SHAPE,
		"calls": WRITE_TRACE,
		"assertions": [
			final_output("modified_script", "regex", r"(?s)^(?!.*\bjson\.)|import json"),
			final_output("modified_script", "regex", r"item_count"),
			NOT_REFUSED,
		],
	},
	{
		"title": "A request for 5 records returns a script that takes 5, not 10",
		"prompt": (
			"List the 5 most recent open ToDo records allocated to the current user and put their "
			"names in result as todos. Only 5, not 10."
		),
		"context": TODO_SHAPE,
		"calls": WRITE_TRACE,
		"assertions": [
			final_output("modified_script", "regex", r"(?<![\w.])5(?![\w.])"),
			final_output("modified_script", "regex", r"^(?![\s\S]*(?<![\w.])10(?![\w.]))"),
			NOT_REFUSED,
		],
	},
	{
		"title": "A client script request never gets a server script back",
		"prompt": "Write a client script for the ToDo form that hides the Description field when Status is Closed.",
		"context": TODO_SHAPE,
		"calls": [call(1, "classify_intent"), call(2, "finalize")],
		"assertions": [
			final_output("response", "regex", r"^(?![\s\S]*```python)"),
			final_output("response", "regex", r"(?i)client script"),
			NOT_REFUSED,
		],
	},
	{
		"title": "A request with no subject gets a question, not the safety refusal",
		"prompt": "prepare a perfect server script",
		"context": BARE_SHAPE,
		"calls": [call(1, "classify_intent"), call(2, "clarify"), call(3, "finalize")],
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "write_script, write_agent_tool"},
			final_output("intent", "equals", "DISAMBIGUATE"),
			NOT_REFUSED,
		],
	},
	{
		"title": "An offer to write a script is answered with a question about what it should do",
		"prompt": "can you generate a script for me?",
		"context": BARE_SHAPE,
		"calls": [call(1, "classify_intent"), call(2, "clarify"), call(3, "finalize")],
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "write_script, write_agent_tool"},
			final_output("intent", "equals", "DISAMBIGUATE"),
			NOT_REFUSED,
		],
	},
	{
		"title": "A pasted function with no error becomes this step's script",
		"prompt": ABSENCE_SCRIPT,
		"context": {
			"element_name": "Populate 21 Days Absence",
			"process_context": script_task(
				"task_populate_absence", "Populate 21 Days Absence", "absence_case"
			),
		},
		"calls": CLASSIFY_THEN_FINALIZE,
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "clarify, write_agent_tool"},
			final_output("intent", "regex", "CREATE|DEBUG_EXISTING"),
			final_output("modified_script", "regex", "Absence Case"),
			NOT_REFUSED,
		],
	},
	{
		"title": "Revert brings back the previous version of the linked script",
		"prompt": "revert your last change. All the script is gone",
		"context": IT_EMPLOYEES_SHAPE,
		"calls": CLASSIFY_THEN_FINALIZE,
		"assertions": [
			{
				"assertion_type": "no_tool_call",
				"value": "write_script, write_agent_tool, clarify, debug_script",
			},
			final_output("intent", "regex", "MODIFY|REVERT"),
			NOT_REFUSED,
		],
	},
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
	judge_provider, judge_model = judge_for(agent)
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["prompt"]
		case.input_context = json.dumps(spec["context"])
		case.set(
			"assertions",
			[
				{**a, "judge_provider": judge_provider, "judge_model": judge_model}
				if a["assertion_type"] == "llm_judge"
				else a
				for a in [ANSWERED_AT_ALL, IN_ORDER, *spec["assertions"]]
			],
		)
		case.set("expected_tool_calls", spec["calls"])
		if existing:
			case.save(ignore_permissions=True)  # patch: seeded eval case
		else:
			case.insert(ignore_permissions=True)  # patch: seeded eval case
