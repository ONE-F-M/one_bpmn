"""Give the Connector and Orchestrator baseline suites a tool-call case each.

Both suites read only what the agent said. That leaves the failure this platform
cares most about invisible: a right answer reached the wrong way. So each gets
one case scored on the trace instead of the text.

The Connector case pins the sequence — the docs are read before a draft exists,
and the draft is reviewed before anything is written. The Orchestrator case pins
that a hand-back is an ACTION: its own prompt says that saying a person is
needed, in a report, hands it to nobody, and only a tool call proves otherwise.

Both are IN_ORDER rather than EXACT. These agents legitimately read the same
reference twice or leave a note on the way past, and a case that fails because
of that teaches its owner to delete the case.

Each case runs against its own fixture, which is cloned from the shape the
suite's existing cases already use — an A2A Task carrying a work order, or a
Work Item on whichever sprint the suite's other items live on. Idempotent, and a
site missing either suite is left alone.
"""

import json

import frappe

CONNECTOR_SUITE = "Connector Agent — Baseline"
ORCHESTRATOR_SUITE = "Orchestrator Agent — Baseline"

CONNECTOR_CASE = "Reads the reference before drafting, and reviews before writing"
ORCHESTRATOR_CASE = "The hand-back is an action, not a sentence in the report"

CONNECTOR_INSTRUCTION = (
	"Build a Processa connector for the Frankfurter exchange-rate API, documented at "
	"https://api.frankfurter.dev/v1/latest . No authentication is required. Cover the operation "
	"that fetches the latest rates."
)

ORCHESTRATOR_WORK_ITEM = {
	"work_item_type": "User Story",
	"title": "Choose the rounding rule for mileage claims",
	"description": (
		"<p>Mileage is currently reimbursed to three decimal places. Finance want it rounded, but "
		"have not said to what — the nearest kilometre, or the nearest 0.5.</p>"
		"<p>Once somebody decides, the change is a couple of lines. Nobody has decided.</p>"
	),
	"status": "Open",
}


def _case(suite: str, title: str, prompt: str, shape: str, context: dict, expected: list) -> None:
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
	case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
	case.suite = suite
	case.title = title
	case.process_model = frappe.db.get_value("AI Eval Suite", suite, "process_model")
	case.bpmn_id = shape
	case.input_user_prompt = prompt
	case.input_context = json.dumps(context)
	case.set("assertions", [{"assertion_type": "tool_calls", "value": "IN_ORDER"}])
	case.set("expected_tool_calls", expected)
	case.save(ignore_permissions=True) if existing else case.insert(ignore_permissions=True)


def _connector(suite: str) -> None:
	title = CONNECTOR_CASE
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
	task = (frappe.parse_json(frappe.db.get_value("AI Eval Case", existing, "input_context") or "{}") or {}).get(
		"context_docname"
	) if existing else None

	if not task or not frappe.db.exists("A2A Task", task):
		previous = frappe.flags.in_patch
		frappe.flags.in_patch = True  # inserting a work order otherwise starts the agent
		try:
			task = frappe.get_doc({
				"doctype": "A2A Task",
				"direction": "Internal",
				"state": "submitted",
				"principal": "Administrator",
				"agent_configuration": frappe.db.get_value("AI Eval Suite", suite, "agent_configuration"),
				"request_payload": json.dumps({"instruction": CONNECTOR_INSTRUCTION}),
			}).insert(ignore_permissions=True).name
		finally:
			frappe.flags.in_patch = previous

	_case(
		suite, title, CONNECTOR_INSTRUCTION, "build_connector",
		{"context_doctype": "A2A Task", "context_docname": task},
		[
			{"call_order": 1, "tool_name": "read_api_docs", "argument": "url",
			 "matcher": "contains", "expected_value": "frankfurter"},
			{"call_order": 2, "tool_name": "draft_connector"},
			{"call_order": 3, "tool_name": "review_connector"},
			{"call_order": 4, "tool_name": "write_connector"},
		],
	)


def _orchestrator(suite: str) -> None:
	title = ORCHESTRATOR_CASE
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
	item = (frappe.parse_json(frappe.db.get_value("AI Eval Case", existing, "input_context") or "{}") or {}).get(
		"context_docname"
	) if existing else None

	if not item or not frappe.db.exists("Work Item", item):
		# Whichever sprint this suite's other fixtures live on: a Work Item
		# cannot exist without one, and inventing a second sprint for one case
		# would put eval scaffolding in two places.
		sprint = None
		for row in frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["input_context"]):
			named = (frappe.parse_json(row.input_context or "{}") or {}).get("context_docname")
			sprint = frappe.db.get_value("Work Item", named, "sprint") if named else None
			if sprint:
				break
		if not sprint:
			frappe.log_error(
				title="add_tool_call_cases_to_agent_suites: no sprint to put the fixture on",
				message=f"None of {suite}'s cases name a Work Item with a sprint; its tool-call case was skipped.",
			)
			return

		previous = frappe.flags.in_patch
		frappe.flags.in_patch = True
		try:
			item = frappe.get_doc({
				"doctype": "Work Item", "sprint": sprint, **ORCHESTRATOR_WORK_ITEM
			}).insert(ignore_permissions=True).name
		finally:
			frappe.flags.in_patch = previous

	_case(
		suite, title, ORCHESTRATOR_WORK_ITEM["title"], "orchestrate",
		{"context_doctype": "Work Item", "context_docname": item},
		[{"call_order": 1, "tool_name": "wi_hand_back"}],
	)


def execute():
	connector = frappe.db.get_value("AI Eval Suite", {"title": CONNECTOR_SUITE}, "name")
	if connector:
		_connector(connector)

	orchestrator = frappe.db.get_value("AI Eval Suite", {"title": ORCHESTRATOR_SUITE}, "name")
	if orchestrator:
		_orchestrator(orchestrator)

	frappe.db.commit()
