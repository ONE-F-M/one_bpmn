"""Seeds five Baseline cases: a brief, ProsAlly's confirmation card, then "Yes, proceed" draws the model.

Idempotent by suite and title.
"""

import json
from pathlib import Path

import frappe

from processa.patches.v1_0.seed_prosally_baseline_suite import AGENT_ID, BASE_ASSERTIONS, SHAPE, SUITE_TITLE

BRIEFS = Path(__file__).with_name("prosally_confirmed_briefs.json")
CALLS = [
	{"call_order": i, "tool_name": tool, "argument": "", "matcher": "", "expected_value": ""}
	for i, tool in enumerate(("classify_intent", "generate_process"), start=1)
]
DRAWN = {
	"assertion_type": "tool_artifact",
	"value": json.dumps(
		{"tool": "generate_process", "path": "ir.lanes", "matcher": "regex", "expected": r"^\[(?!\])"}
	),
}


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return
	suite = frappe.db.get_value("AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}, "name")
	if not suite:
		return
	for spec in json.loads(BRIEFS.read_text()):
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = "Yes, proceed"
		case.input_context = json.dumps(
			{
				"conversation_messages": [
					{"message_type": "User", "text": spec["brief"]},
					{
						"message_type": "Bot",
						"text": spec["confirmation"],
						"metadata": {"intent": "CONFIRM", "agent_result": {"action_intent": "GENERATE_NEW"}},
					},
				]
			}
		)
		case.set(
			"assertions",
			[
				*BASE_ASSERTIONS,
				{"assertion_type": "no_tool_call", "value": "clarify, redirect, confirm"},
				DRAWN,
			],
		)
		case.set("expected_tool_calls", CALLS)
		if existing:
			case.save(ignore_permissions=True)  # patch: seeded eval case
		else:
			case.insert(ignore_permissions=True)  # patch: seeded eval case
