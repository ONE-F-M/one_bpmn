"""Seed ProsAlly's baseline eval suite: generate turns scored on the diagram, not the reply.

Each case arrives already confirmed, so the turn is classify_intent then generate_process, where it stops.
The lanes are read off the IR generate_process records as its artifact, which only follow the
lane rules when the stage skills reached the generator. Idempotent by suite and case title.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import _call

AGENT_ID = "prosally_agent"
SHAPE = "run_prosally_agent"
SUITE_TITLE = "ProsAlly - Baseline"

SUITE_DESCRIPTION = (
	"ProsAlly through a real, already-confirmed generate turn. Every case checks the trace up to "
	"generate_process, that the orchestrator never loads a skill, and the lanes in the IR generate_process "
	"recorded. Each case spends one generator call."
)

CONFIRMED = {"confirmed_action": "GENERATE_NEW"}
# A stage tool that writes the reply ends the turn, so finalize is never called after it.
GENERATE_TRACE = [_call(1, "classify_intent"), _call(2, "generate_process")]


def _lanes(matcher, expected):
	return {
		"assertion_type": "tool_artifact",
		"value": json.dumps(
			{"tool": "generate_process", "path": "ir.lanes.name", "matcher": matcher, "expected": expected}
		),
	}


BASE_ASSERTIONS = [
	{"assertion_type": "tool_calls", "value": "IN_ORDER"},
	{"assertion_type": "no_tool_call", "value": "load_skill, unload_skill, load_skill_resource"},
]

CASES = [
	{
		"title": "Named lanes are drawn exactly, with no system lane added",
		"prompt": (
			"Create a Visa Request process with 3 lanes only: Recruiter, GRD Operator, GRD Manager. "
			"The recruiter raises the request, the GRD Operator prepares the documents and emails the "
			"recruiter, and the GRD Manager approves or rejects it."
		),
		"assertions": [*BASE_ASSERTIONS, _lanes("equals", ["Recruiter", "GRD Operator", "GRD Manager"])],
	},
	{
		"title": "With no lanes named, automated steps get a system lane",
		"prompt": (
			"Create a leave request process: the employee submits a leave request, the system checks "
			"the leave balance and emails the employee the result."
		),
		"assertions": [*BASE_ASSERTIONS, _lanes("contains", "System (Automatic)")],
	},
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return

	suite = _suite(agent, process_model)
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["prompt"]
		case.input_context = json.dumps(CONFIRMED)
		case.set("assertions", spec["assertions"])
		case.set("expected_tool_calls", GENERATE_TRACE)
		if existing:
			case.save(ignore_permissions=True)
		else:
			case.insert(ignore_permissions=True)


def _suite(agent: str, process_model: str) -> str:
	values = {
		"eval_type": "Agent",
		"suite_type": "Baseline",
		"process_model": process_model,
		"agent_configuration": agent,
		"description": SUITE_DESCRIPTION,
	}
	existing = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if existing:
		frappe.db.set_value("AI Eval Suite", existing, values)
		return existing
	return frappe.get_doc({"doctype": "AI Eval Suite", "title": SUITE_TITLE, **values}).insert(
		ignore_permissions=True
	).name
