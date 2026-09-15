# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A worked example of the two tool-call modes nothing else uses.

Every trajectory case in the estate is IN_ORDER, which is the right everyday
choice — agents legitimately re-read a reference or leave a note on the way
past. It also means EXACT and ANY_ORDER exist only in unit tests, and a mode
nobody has run is a mode nobody can trust.

Two cases, each picked so its mode is the honest one to use:

* **ANY_ORDER** — a documented API is read and a connector written. Both calls
  must happen; which comes first is the agent's business, and a case that
  insisted would be asserting a preference rather than a requirement.
* **EXACT** — handed a work order with nothing in it, the agent should read,
  find nothing, and stop. "Nothing else happened" is the whole point, and EXACT
  is the only mode that can say it.

Its own suite, deliberately. The Connector baseline gates deployment at 75%,
and a case about a mode we are still learning the shape of should not be able
to block a release. No CI role, so nothing runs it unattended.
"""

import json

import frappe

AGENT = "Connector Agent"
MAP = "Connector Agent"
SHAPE = "build_connector"
SUITE = "Connector Agent — Trajectory Modes"

DESCRIPTION = (
	"Worked examples of the EXACT and ANY_ORDER tool-call modes. Not a gate: these measure "
	"how the modes behave, not whether the agent may ship."
)

CASES = [
	{
		"title": "ANY_ORDER — the reference is read and the connector written, in either order",
		"prompt": (
			"Build a Processa connector for the Frankfurter exchange-rate API, documented at "
			"https://api.frankfurter.dev/v1/latest . No authentication is required."
		),
		"expected": "A connector covering the latest-rates operation, left disabled.",
		"mode": "ANY_ORDER",
		"calls": [
			{"call_order": 1, "tool_name": "read_api_docs"},
			{"call_order": 2, "tool_name": "write_connector"},
		],
		"assertions": [{"assertion_type": "tool_calls", "value": "ANY_ORDER"}],
	},
	{
		"title": "EXACT — given no work order, it reads, finds nothing, and stops",
		"prompt": "",
		"expected": "Says there is no work order to act on, and does nothing else.",
		"mode": "EXACT",
		"calls": [
			{"call_order": 1, "tool_name": "read_work_item"},
			{"call_order": 2, "tool_name": "finalize"},
		],
		"assertions": [
			{"assertion_type": "tool_calls", "value": "EXACT"},
			# A run that produced nothing would otherwise fail on the trace alone,
			# and read as the agent having done the wrong thing rather than nothing.
			{"assertion_type": "regex", "value": r"\S"},
		],
	},
]


def _fixture(case: str | None, instruction: str) -> str:
	"""The A2A Task a case runs against, created once and reused."""
	if case:
		named = (frappe.parse_json(frappe.db.get_value("AI Eval Case", case, "input_context") or "{}") or {}).get(
			"context_docname"
		)
		if named and frappe.db.exists("A2A Task", named):
			return named

	frappe.flags.in_patch = True  # an A2A Task landing normally starts the agent
	try:
		return frappe.get_doc({
			"doctype": "A2A Task",
			"direction": "Inbound",
			"state": "submitted",
			"agent_configuration": AGENT,
			"request_payload": json.dumps({"instruction": instruction}),
		}).insert(ignore_permissions=True).name
	finally:
		frappe.flags.in_patch = False


def _suite() -> str:
	existing = frappe.db.get_value("AI Eval Suite", {"title": SUITE}, "name")
	fields = {
		"eval_type": "Agent",
		"suite_type": "Baseline",
		"process_model": MAP,
		"agent_configuration": AGENT,
		"description": DESCRIPTION,
		"pass_k": 1,
		"min_pass_rate": 0,
		"gate_deployment": 0,
	}
	if existing:
		frappe.db.set_value("AI Eval Suite", existing, fields)
		return existing
	doc = frappe.get_doc({"doctype": "AI Eval Suite", "title": SUITE, **fields})
	doc.flags.ignore_mandatory = True
	return doc.insert(ignore_permissions=True).name


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT) or not frappe.db.exists("BPMN Process Model", MAP):
		print(f"seed_connector_trajectory_modes: no {AGENT!r} on this site — skipped")
		return

	suite = _suite()
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		task = _fixture(existing, spec["prompt"])
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.process_model = MAP
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["prompt"]
		case.input_context = json.dumps({"context_doctype": "A2A Task", "context_docname": task})
		case.expected_output = spec["expected"]
		case.set("assertions", [])
		for assertion in spec["assertions"]:
			case.append("assertions", assertion)
		case.set("expected_tool_calls", [])
		for call in spec["calls"]:
			case.append("expected_tool_calls", call)
		case.flags.ignore_mandatory = True
		case.save(ignore_permissions=True) if existing else case.insert(ignore_permissions=True)

	frappe.db.commit()
	print(f"seed_connector_trajectory_modes: {SUITE} — {len(CASES)} case(s)")
