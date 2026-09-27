"""Seed LuCrusher's baseline eval suite: six cases across the phases real users go through.

Cases 4 to 6 start from earlier turns: the runner writes their conversation_messages and
session_state into the case's conversation before the test message. Each case checks the
finalize intent through expected_tool_calls. Idempotent by suite and case title; a site
without LuCrusher is left alone.
"""

import json

import frappe

AGENT_ID = "lucrusher_agent"
SHAPE = "run_lucrusher_agent"
SUITE_TITLE = "LuCrusher - Baseline"
JUDGE_PROVIDER = "Anthropic"
JUDGE_MODEL = "claude-sonnet-4-5-20250929"
PASS_K = 5
MIN_PASS_RATE = 90

LUCID_DOC_ID = "f09e07ba-68d4-4228-972c-a0a90b38f76d"
LUCID_URL = f"https://lucid.app/lucidchart/{LUCID_DOC_ID}/edit?page=0_0#"
STATE_TEXT = "__lucrusher_state__"

SUITE_DESCRIPTION = (
	"LuCrusher through a real chat turn: process search, Lucidchart fetch, the same link again, "
	"codebase scan and topology confirmation. Every case checks the intent LuCrusher passes to "
	"finalize. The Lucidchart case calls the real Lucid API and needs lucidchart_api_key; the "
	"repeat-link case seeds the fetched document, so it passes without the API."
)

PARSED_DOC = {
	"document_id": LUCID_DOC_ID,
	"title": "Visa Process",
	"page_count": 2,
	"total_shapes": 12,
	"total_lines": 10,
	"pages": [
		{"page_title": "Visa Request", "shape_count": 7},
		{"page_title": "Visa Renewal", "shape_count": 5},
	],
}
DOC_SUMMARY = {"document_id": LUCID_DOC_ID, "title": "Visa Process", "page_count": 2}
SCAN_SUMMARY = {"apps_scanned": ["one_fm", "hrms"], "matched_doctypes": ["Visa", "Residency Permit"]}
TOPOLOGY = {
	"total_processes": 2,
	"processes": [{"process_name": "Visa Request"}, {"process_name": "Visa Renewal"}],
}


def _state(intent, **parts):
	return {
		"intent": intent,
		"confirmed_process": {"name": "Visa", "process_name": "Visa"},
		"document": None,
		"codebase_scan": None,
		"topology": None,
		"migration_tasks": None,
		"prosally_prompts": None,
		**parts,
	}


def _call(order, tool, argument="", matcher="", value=""):
	return {
		"call_order": order,
		"tool_name": tool,
		"argument": argument,
		"matcher": matcher,
		"expected_value": value,
	}


def _judge(rubric):
	return {
		"assertion_type": "llm_judge",
		"value": rubric,
		"judge_provider": JUDGE_PROVIDER,
		"judge_model": JUDGE_MODEL,
		"pass_threshold": 4,
	}


IN_ORDER = {"assertion_type": "tool_calls", "value": "IN_ORDER"}

CASES = [
	{
		"title": "A process name with one exact match",
		"prompt": "Visa",
		"context": {},
		"calls": [
			_call(1, "search_processes_on_production", "search_term", "contains", "Visa"),
			_call(2, "finalize", "intent", "equals", "EXACT_MATCH_FOUND"),
		],
		"assertions": [
			IN_ORDER,
			{"assertion_type": "no_tool_call", "value": "fetch_lucidchart_document,scan_codebase_for_process"},
		],
	},
	{
		"title": "A keyword with several matches",
		"prompt": "Maintenance",
		"context": {},
		"calls": [
			_call(1, "search_processes_on_production", "search_term", "contains", "Maintenance"),
			_call(2, "finalize", "intent", "equals", "MULTIPLE_MATCHES"),
		],
		"assertions": [
			IN_ORDER,
			_judge(
				"The reply lists more than one matching process and asks the user which one they mean. "
				"It does not pick one on the user's behalf."
			),
		],
	},
	{
		"title": "A Lucidchart link is fetched and parsed",
		"prompt": f"I would like you to review {LUCID_URL}",
		"context": {},
		"calls": [
			_call(1, "fetch_lucidchart_document", "document_id_or_url", "contains", LUCID_DOC_ID),
			_call(2, "finalize", "intent", "regex", "^LUCIDCHART_(PARSED|METADATA_ONLY)$"),
		],
		"assertions": [IN_ORDER],
	},
	{
		"title": "The same Lucidchart link again uses the fetched copy",
		"prompt": LUCID_URL,
		"context": {
			"conversation_messages": [
				{"message_type": "User", "text": LUCID_URL},
				{
					"message_type": "Bot",
					"text": 'I fetched "Visa Process": 2 pages, Visa Request and Visa Renewal, 12 shapes.',
				},
				{"message_type": "Tool", "text": STATE_TEXT, "metadata": _state("LUCIDCHART_PARSED", document=DOC_SUMMARY)},
			],
			"session_state": {f"lucid_doc:{LUCID_DOC_ID}": PARSED_DOC},
		},
		"calls": [_call(1, "finalize", "intent", "regex", "^(CLARIFY|LUCIDCHART_PARSED|LUCIDCHART_METADATA_ONLY)$")],
		"assertions": [
			IN_ORDER,
			{"assertion_type": "no_tool_call", "value": "fetch_lucidchart_document,scan_codebase_for_process"},
			_judge(
				"The reply tells the user the Visa Process document is already loaded and waits for their next "
				"instruction. It does not report an error, say it fetched the document again, or start a codebase scan."
			),
		],
	},
	{
		"title": "A codebase scan after the document is fetched",
		"prompt": (
			"scan the codebase for the Visa process: Visa Request, Visa Approval, Visa Renewal, "
			"Residency Permit"
		),
		"context": {
			"conversation_messages": [
				{"message_type": "User", "text": LUCID_URL},
				{"message_type": "Bot", "text": 'I fetched "Visa Process": 2 pages, 12 shapes.'},
				{"message_type": "Tool", "text": STATE_TEXT, "metadata": _state("LUCIDCHART_PARSED", document=DOC_SUMMARY)},
			],
			"session_state": {f"lucid_doc:{LUCID_DOC_ID}": PARSED_DOC},
		},
		"calls": [
			_call(1, "scan_codebase_for_process"),
			_call(2, "finalize", "intent", "equals", "CODEBASE_SCAN_RESULT"),
		],
		"assertions": [IN_ORDER],
	},
	{
		"title": "Confirming the proposed topology",
		"prompt": "yes, the topology looks good",
		"context": {
			"conversation_messages": [
				{"message_type": "User", "text": "analyse the topology for this process"},
				{
					"message_type": "Bot",
					"text": (
						"I propose 2 processes: Visa Request and Visa Renewal. "
						"Does this topology look right?"
					),
				},
				{
					"message_type": "Tool",
					"text": STATE_TEXT,
					"metadata": _state(
						"TOPOLOGY_PROPOSAL", document=DOC_SUMMARY, codebase_scan=SCAN_SUMMARY, topology=TOPOLOGY
					),
				},
			],
			"session_state": {f"lucid_doc:{LUCID_DOC_ID}": PARSED_DOC},
		},
		"calls": [_call(1, "finalize", "intent", "equals", "TOPOLOGY_CONFIRMED")],
		"assertions": [
			IN_ORDER,
			{"assertion_type": "no_tool_call", "value": "fetch_lucidchart_document,scan_codebase_for_process"},
			_judge(
				"The reply confirms the two processes, Visa Request and Visa Renewal, as the agreed topology "
				"and moves on to the next step. It does not propose a different topology."
			),
		],
	},
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return

	if not frappe.db.exists("AI Model", JUDGE_MODEL):
		frappe.log_error(
			title="seed_lucrusher_eval_suite: judge model missing",
			message=f"No AI Model '{JUDGE_MODEL}' on this site; the llm_judge assertions will error until it exists.",
		)

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
		case.input_context = json.dumps(spec["context"]) if spec["context"] else None
		case.set("assertions", spec["assertions"])
		case.set("expected_tool_calls", spec["calls"])
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
		"pass_k": PASS_K,
		"min_pass_rate": MIN_PASS_RATE,
	}
	existing = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if existing:
		frappe.db.set_value("AI Eval Suite", existing, values)
		return existing
	return frappe.get_doc({"doctype": "AI Eval Suite", "title": SUITE_TITLE, **values}).insert(
		ignore_permissions=True
	).name
