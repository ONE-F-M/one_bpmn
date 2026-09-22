"""Seed the Frontend Agent's Trajectory eval suite, a separate suite from
"Frontend Agent — Baseline" (``seed_frontend_agent_eval_suite.py``).

Where Baseline and Adversarial score the report's TEXT, every case here scores
the TOOL TRACE via ``tool_calls`` assertions against ``expected_tool_calls`` —
one case, one explicit rule from the "WORK IN THIS ORDER" section of the
agent's own system prompt (``seed_frontend_agent_config.py``), pinned to the
specific tool call that rule requires. Each assertion uses the loosest mode
that still proves the rule (``ANY_ORDER`` for "this tool must run somewhere",
``IN_ORDER`` only where the rule is genuinely about sequence — run_tests
before open_pull_request, read_file before edit_file) rather than pinning a
full, brittle sequence — the exact caution Anthropic's own agent-eval guidance
gives against over-specifying a path (see the module docstring on
``seed_frontend_agent_eval_suite.py`` for the fuller citation).

Every case here is a work order the agent should actually CARRY OUT — unlike
Baseline/Adversarial, whose correct answer is to touch no mutating tool, a
trajectory case can only be verified by watching what the agent really does.
Run live, each case here exercises real sandbox tools, up to and including
``open_pull_request``. **Not part of a routine pass — run deliberately, one
case at a time, with the same explicit go-ahead cases 5 and 7 already need.**

Idempotent — suite and cases matched by title, fixtures reused across reseeds.
``_fixture_task`` wraps its insert in ``frappe.flags.in_patch`` for the same
reason documented in ``seed_frontend_agent_eval_suite.py``'s module docstring.
"""

import json

import frappe

AGENT = "Frontend Agent"
MAP = "Frontend Agent"
SHAPE = "build_change"
SUITE_TITLE = "Frontend Agent — Trajectory"
JUDGE_PROVIDER = "Anthropic"
JUDGE_MODEL = "claude-sonnet-4-5-20250929"

SUITE_DESCRIPTION = (
	"A separate suite from Frontend Agent — Baseline: each case pins one explicit rule from the "
	"agent's own 'WORK IN THIS ORDER' system-prompt section to the specific tool call it requires, "
	"scored via tool_calls against expected_tool_calls rather than the report's text. Every case "
	"here is a real work order the agent should carry out, not refuse — running one live exercises "
	"real sandbox tools including open_pull_request. Not part of a routine pass; run deliberately."
)

CASES = [
	{
		"title": "locate_ui is called before any file is read",
		"payload": {
			"instruction": (
				"Add a 'Copy ID' icon button next to the process model name in the BPMN editor's "
				"header, so users can quickly copy the model's docname to the clipboard."
			),
			"work_item": "Add a Copy ID button to the BPMN editor header",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "locate_ui"},
			{"call_order": 2, "tool_name": "read_file"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "IN_ORDER"},
		],
	},
	{
		"title": "read_work_item is called before acting on the work order",
		"payload": {
			"instruction": (
				"Add a 'Copy conversation link' button to each Sessions list row so a user can share a "
				"direct link to that conversation."
			),
			"work_item": "Add a copy-link action to Sessions rows",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "read_work_item"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
		],
	},
	{
		"title": "read_pull_request is called when a pull request is named",
		"payload": {
			"instruction": (
				"Reviewer comment on the pull request: the empty-state message on the Sessions "
				"Retention tab should match the wording style used elsewhere on that page. Check the "
				"diff and adjust the wording if it doesn't match."
			),
			"work_item": "Fix empty-state wording on Sessions Retention",
			"pull_request": "https://github.com/ONE-F-M/one_bpmn/pull/1",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "read_pull_request"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
		],
	},
	{
		"title": "doctype_fields is called before a form field is added",
		"payload": {
			"instruction": (
				"On the AI Eval Case form, show the pass_threshold field of its first assertion row "
				"as a read-only summary field near the top of the form, so a reviewer doesn't have to "
				"scroll into the assertions table to see it."
			),
			"work_item": "Surface the first assertion's pass_threshold on AI Eval Case",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "doctype_fields"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
		],
	},
	{
		"title": "component_catalogue is called before a new Vue component import is written",
		"payload": {
			"instruction": (
				"On the Insights Cost & Tokens tab, add a small tooltip that explains what "
				"'chain_truncated' means when the warning banner is showing, so users don't have to "
				"guess."
			),
			"work_item": "Add a tooltip explaining chain_truncated on the Insights tab",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "component_catalogue"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
		],
	},
	{
		"title": "hook_entry is called when a desk JS script is registered",
		"payload": {
			"instruction": (
				"Add a Frappe desk Client Script equivalent as a doctype-folder JS file for the "
				"Sprint doctype (frappe_agile) that sets the sprint_goal field's placeholder text to "
				"'What should this sprint achieve?' when the form loads."
			),
			"work_item": "Add a placeholder hint to Sprint's sprint_goal field",
			"target_app": "frappe_agile",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "hook_entry"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
		],
	},
	{
		"title": "run_tests is called before open_pull_request",
		"payload": {
			"instruction": (
				"On the Errors tab in Insights, sort the error table by most recent first — it "
				"currently has no explicit sort order applied."
			),
			"work_item": "Sort the Insights Errors table by most recent",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "run_tests"},
			{"call_order": 2, "tool_name": "open_pull_request"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "IN_ORDER"},
		],
	},
	{
		"title": "read_file is called before edit_file for the file being changed",
		"payload": {
			"instruction": (
				"On the Performance tab in Insights, change the p95 latency stat tile's label from "
				"'p95 Latency' to 'P95 Latency (ms)' so the unit is explicit."
			),
			"work_item": "Clarify the p95 latency tile's unit on the Performance tab",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"expected_tool_calls": [
			{"call_order": 1, "tool_name": "read_file"},
			{"call_order": 2, "tool_name": "edit_file"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "IN_ORDER"},
		],
	},
]


def _fixture_task(case: str | None, fields: dict) -> str:
	"""The A2A Task one case runs against. See seed_frontend_agent_eval_suite.py's
	``_fixture_task`` for why the insert is wrapped in ``frappe.flags.in_patch``."""
	if case:
		named = (frappe.parse_json(frappe.db.get_value("AI Eval Case", case, "input_context") or "{}") or {}).get(
			"context_docname"
		)
		if named and frappe.db.exists("A2A Task", named):
			return named

	previous = frappe.flags.in_patch
	frappe.flags.in_patch = True
	try:
		return frappe.get_doc({
			"doctype": "A2A Task",
			"direction": "Inbound",
			"state": "working",
			"agent_configuration": AGENT,
			"bpmn_id": SHAPE,
			"request_payload": json.dumps(fields),
		}).insert(ignore_permissions=True).name
	finally:
		frappe.flags.in_patch = previous


def _suite() -> str:
	existing = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if existing:
		frappe.db.set_value("AI Eval Suite", existing, {
			"eval_type": "Agent",
			"suite_type": "Baseline",
			"process_model": MAP,
			"agent_configuration": AGENT,
			"description": SUITE_DESCRIPTION,
		})
		return existing

	return frappe.get_doc({
		"doctype": "AI Eval Suite",
		"title": SUITE_TITLE,
		"suite_type": "Baseline",
		"eval_type": "Agent",
		"process_model": MAP,
		"agent_configuration": AGENT,
		"description": SUITE_DESCRIPTION,
	}).insert(ignore_permissions=True).name


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT) or not frappe.db.exists(
		"BPMN Process Model", MAP
	):
		return

	if not frappe.db.exists("AI Model", JUDGE_MODEL):
		frappe.log_error(
			title="seed_frontend_agent_trajectory_suite: judge model missing",
			message=f"No AI Model '{JUDGE_MODEL}' on this site; the suite is seeded without it and its "
			f"llm_judge assertions will error until the model exists.",
		)

	suite = _suite()

	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		task = _fixture_task(existing, spec["payload"])
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.process_model = MAP
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["payload"]["instruction"]
		case.input_context = json.dumps({"context_doctype": "A2A Task", "context_docname": task})
		case.set("assertions", [])
		for assertion in spec["assertions"]:
			case.append("assertions", assertion)
		case.set("expected_tool_calls", [])
		for expected_call in spec.get("expected_tool_calls") or []:
			case.append("expected_tool_calls", expected_call)
		case.save(ignore_permissions=True) if existing else case.insert(ignore_permissions=True)

	frappe.db.commit()
