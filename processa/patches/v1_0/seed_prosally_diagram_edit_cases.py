"""Seeds four Baseline cases: ProsAlly adds a named sub-process to a saved diagram without a redraw.

Idempotent by suite and case title.
"""

import json

import frappe

from processa.patches.v1_0.prosally_turns_a_step_into_a_subprocess import SUITE_TITLE, fixture_xml
from processa.patches.v1_0.seed_prosally_baseline_suite import AGENT_ID, SHAPE

PROMPTS = (
	("Payroll Operator", "Add a Payroll Operator sub-process after Complete Payroll Clearance"),
	("PCC", "Add a PCC sub-process after Call Closure"),
	("Medical", "Add a Medical sub-process"),
	("Visa Stamping", "Add a Visa Stamping sub-process after Complete Payroll Clearance"),
)


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite:
		return
	context = json.dumps({"current_xml": fixture_xml(), "process_name": "Employee Offboarding"})
	for name, prompt in PROMPTS:
		title = f"Adding the {name} sub-process edits the saved diagram without a redraw"
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = title
		case.case_type = "Trajectory"
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = prompt
		case.input_context = context
		case.set(
			"assertions",
			[
				{"assertion_type": "contains", "value": f'I added the sub-process "{name}"'},
				{"assertion_type": "no_tool_call", "value": "modify_process, generate_process"},
			],
		)
		case.set(
			"expected_tool_calls", [{"call_order": 1, "tool_name": "classify_intent", "matcher": "equals"}]
		)
		if existing:
			case.save(ignore_permissions=True)  # patch: seeded eval case
		else:
			case.insert(ignore_permissions=True)  # patch: seeded eval case
