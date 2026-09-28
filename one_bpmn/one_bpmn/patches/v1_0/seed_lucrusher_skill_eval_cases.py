"""LuCrusher Baseline gains four cases for Phases 4 to 6 and their skills.

Each drafting case checks that the turn loads its phase skill before finalize; the
confirmation case checks that it loads none. Idempotent by suite and case title.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import (
	AGENT_ID,
	DOC_SUMMARY,
	IN_ORDER,
	LUCID_DOC_ID,
	PARSED_DOC,
	SCAN_SUMMARY,
	SHAPE,
	STATE_TEXT,
	SUITE_TITLE,
	TOPOLOGY,
	_call,
	_judge,
	_state,
	judge_for,
)
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL, TASKS_SKILL, TOPOLOGY_SKILL

NO_REFETCH = {
	"assertion_type": "no_tool_call",
	"value": "fetch_lucidchart_document,scan_codebase_for_process",
}
SESSION = {f"lucid_doc:{LUCID_DOC_ID}": PARSED_DOC}

MIGRATION_TASKS = {
	"processes": [
		{
			"process_name": name,
			"tasks": [
				{
					"category": "PROCESS MAP",
					"task": f"Build the {name} map",
					"detail": "",
					"references": "",
					"is_new": True,
				}
			],
		}
		for name in ("Visa Request", "Visa Renewal")
	]
}


def _turn(user_text, bot_text, state):
	return {
		"conversation_messages": [
			{"message_type": "User", "text": user_text},
			{"message_type": "Bot", "text": bot_text},
			{"message_type": "Tool", "text": STATE_TEXT, "metadata": state},
		],
		"session_state": SESSION,
	}


CASES = [
	{
		"title": "Analysing the topology loads the topology skill",
		"skill": TOPOLOGY_SKILL,
		"prompt": "analyse the topology for this process",
		"context": _turn(
			"scan the codebase for the Visa process",
			"The scan found 2 apps and 2 DocTypes: Visa and Residency Permit.",
			_state("CODEBASE_SCAN_RESULT", document=DOC_SUMMARY, codebase_scan=SCAN_SUMMARY),
		),
		"calls": [
			_call(1, "load_skill", "skill_name", "equals", TOPOLOGY_SKILL),
			_call(2, "finalize", "intent", "equals", "TOPOLOGY_PROPOSAL"),
		],
		"assertions": [IN_ORDER, NO_REFETCH],
	},
	{
		"title": "Generating migration tasks loads the migration task skill",
		"skill": TASKS_SKILL,
		"prompt": "generate the migration tasks",
		"context": _turn(
			"yes, the topology looks good",
			"Topology confirmed: Visa Request and Visa Renewal. Next I can generate the migration tasks.",
			_state("TOPOLOGY_CONFIRMED", document=DOC_SUMMARY, codebase_scan=SCAN_SUMMARY, topology=TOPOLOGY),
		),
		"calls": [
			_call(1, "load_skill", "skill_name", "equals", TASKS_SKILL),
			_call(2, "finalize", "intent", "equals", "MIGRATION_TASKS_DRAFT"),
		],
		"assertions": [IN_ORDER, NO_REFETCH],
	},
	{
		"title": "Writing ProsAlly prompts loads the ProsAlly skill",
		"skill": PROSALLY_SKILL,
		"prompt": "now write the ProsAlly prompts",
		"context": _turn(
			"approved",
			"Migration tasks confirmed. Next I can write the ProsAlly prompts.",
			_state(
				"MIGRATION_TASKS_CONFIRMED",
				document=DOC_SUMMARY,
				codebase_scan=SCAN_SUMMARY,
				topology=TOPOLOGY,
				migration_tasks=MIGRATION_TASKS,
			),
		),
		"calls": [
			_call(1, "load_skill", "skill_name", "equals", PROSALLY_SKILL),
			_call(2, "finalize", "intent", "equals", "PROSALLY_PROMPT_DRAFT"),
		],
		"assertions": [
			IN_ORDER,
			NO_REFETCH,
			_judge(
				"prosally_prompts holds exactly two processes, Visa Request and Visa Renewal, and each "
				"prompt_block has a header, lanes, elements, sequence flows and an anti-linting section."
			),
		],
	},
	{
		"title": "Approving migration tasks loads no skill",
		"skill": TASKS_SKILL,
		"prompt": "approved",
		"context": _turn(
			"generate the migration tasks",
			"I drafted 2 tasks across 2 processes. Do they look right?",
			_state(
				"MIGRATION_TASKS_DRAFT",
				document=DOC_SUMMARY,
				codebase_scan=SCAN_SUMMARY,
				topology=TOPOLOGY,
				migration_tasks=MIGRATION_TASKS,
			),
		),
		"calls": [_call(1, "finalize", "intent", "equals", "MIGRATION_TASKS_CONFIRMED")],
		"assertions": [IN_ORDER, {"assertion_type": "no_tool_call", "value": "load_skill"}],
	},
]


def execute():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	suite, process_model = frappe.db.get_value(
		"AI Eval Suite", {"title": SUITE_TITLE}, ["name", "process_model"]
	) or (None, None)
	if not agent or not suite:
		return

	judge_provider, judge_model = judge_for(agent)
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.target_skill = spec["skill"]
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["prompt"]
		case.input_context = json.dumps(spec["context"])
		# A site with no enabled judge model keeps the tool-call checks and drops the judge check.
		case.set(
			"assertions",
			[
				{**a, "judge_provider": judge_provider, "judge_model": judge_model}
				if a["assertion_type"] == "llm_judge"
				else a
				for a in spec["assertions"]
				if judge_model or a["assertion_type"] != "llm_judge"
			],
		)
		case.set("expected_tool_calls", spec["calls"])
		if existing:
			case.save(ignore_permissions=True)
		else:
			case.insert(ignore_permissions=True)
