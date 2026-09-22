"""Seed the Frontend Agent's Co-Load Budget eval suite, a separate suite from
"Frontend Agent — Baseline" (``seed_frontend_agent_eval_suite.py``).

Every case here is a routine, well-specified work order — nothing adversarial,
nothing missing — scored only on ``max_tokens``: does an ordinary change stay
inside a sane token ceiling, or does the agent burn an outsized amount of
budget on work that should be straightforward. Distinct from case 5 on the
Baseline suite (``seed_frontend_agent_eval_suite.py``), which reproduces a
KNOWN pathological work order (a real turn-cap loop from BA) — these cases are
the opposite: ordinary requests, the kind most work orders actually look like,
so a budget regression here is a genuine cost/efficiency signal rather than a
known hard case.

Run live, both cases exercise real sandbox tools including ``open_pull_request``
— not part of a routine pass; run deliberately, same as the Trajectory suite.

Idempotent — suite and cases matched by title, fixtures reused across reseeds.
``_fixture_task`` wraps its insert in ``frappe.flags.in_patch`` for the same
reason documented in ``seed_frontend_agent_eval_suite.py``'s module docstring.
"""

import json

import frappe

AGENT = "Frontend Agent"
MAP = "Frontend Agent"
SHAPE = "build_change"
SUITE_TITLE = "Frontend Agent — Co-Load Budget"
JUDGE_PROVIDER = "Anthropic"
JUDGE_MODEL = "claude-sonnet-4-5-20250929"

SUITE_DESCRIPTION = (
	"A separate suite from Frontend Agent — Baseline: ordinary, well-specified work orders scored "
	"only on max_tokens — does a routine change stay inside a sane token budget. Unlike case 5's "
	"known pathological turn-cap loop, these are the ordinary shape most real work orders take, so "
	"a regression here is a genuine cost signal. Run live, both cases exercise real sandbox tools "
	"including open_pull_request; not part of a routine pass, run deliberately."
)

CASES = [
	{
		"title": "A routine single-file change stays inside its token budget",
		"payload": {
			"instruction": (
				"On the Home view (spiff/src/views/Home.vue), change the welcome heading text from "
				"'Welcome' to 'Welcome back' — a single string literal change."
			),
			"work_item": "Update the Home welcome heading text",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"assertions": [
			{"assertion_type": "max_tokens", "value": "300000"},
		],
	},
	{
		"title": "A small multi-file component build stays inside its token budget",
		"payload": {
			"instruction": (
				"Add a small 'Last synced' badge component (new file, spiff/src/components/"
				"LastSyncedBadge.vue) that takes a `timestamp` prop and shows a relative time string "
				"('2 minutes ago', 'just now'), and use it in the BA Sync section of Processa Settings' "
				"desk form area — following whatever relative-time helper existing components already "
				"use, if one exists, rather than adding a new dependency."
			),
			"work_item": "Add a Last Synced badge to the BA Sync section",
			"target_app": "one_bpmn",
			"git_branch": "staging",
		},
		"assertions": [
			{"assertion_type": "max_tokens", "value": "600000"},
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
			title="seed_frontend_agent_coload_budget_suite: judge model missing",
			message=f"No AI Model '{JUDGE_MODEL}' on this site; the suite is seeded without it.",
		)

	suite = _suite()

	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		task = _fixture_task(existing, spec["payload"])
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Co-Load Budget"
		case.process_model = MAP
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["payload"]["instruction"]
		case.input_context = json.dumps({"context_doctype": "A2A Task", "context_docname": task})
		case.set("assertions", [])
		for assertion in spec["assertions"]:
			case.append("assertions", assertion)
		case.save(ignore_permissions=True) if existing else case.insert(ignore_permissions=True)

	frappe.db.commit()
