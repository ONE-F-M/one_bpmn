"""LuCrusher Baseline gains four cases where the latest request, not the stored phase, picks the output.

A migration list, the code to remove and the topology each get their own answer, and a request that
names no phase is asked about. Idempotent by suite and case title.
"""

from processa.patches.v1_0.seed_lucrusher_eval_suite import (
	DOC_SUMMARY,
	IN_ORDER,
	LUCID_DOC_ID,
	PARSED_DOC,
	SCAN_SUMMARY,
	TOPOLOGY,
	_call,
	_judge,
	_state,
)
from processa.patches.v1_0.seed_lucrusher_skill_eval_cases import MIGRATION_TASKS, NO_REFETCH, seed_cases
from processa.patches.v1_0.seed_lucrusher_skills import TASKS_SKILL, TOPOLOGY_SKILL


def _context(bot_text, intent, **parts):
	state = {
		k: v
		for k, v in _state(intent, document=DOC_SUMMARY, codebase_scan=SCAN_SUMMARY, **parts).items()
		if v
	}
	return {
		"conversation_messages": [
			{"message_type": "User", "text": "analyse the topology for this process"},
			{"message_type": "Bot", "text": bot_text},
		],
		"session_state": {f"lucid_doc:{LUCID_DOC_ID}": PARSED_DOC, **state},
	}


PROPOSED = _context(
	"I propose two processes: Visa Request and Visa Renewal. Shall I go ahead?",
	"TOPOLOGY_PROPOSAL",
	topology=TOPOLOGY,
)

CASES = [
	{
		"title": "A migration list request gets the migration tasks, not the topology",
		"skill": TASKS_SKILL,
		"prompt": "give me the migration list",
		"context": PROPOSED,
		"calls": [_call(1, "finalize", "intent", "equals", "MIGRATION_TASKS_DRAFT")],
		"assertions": [IN_ORDER, NO_REFETCH],
	},
	{
		"title": "A code removal request gets only the code to remove",
		"skill": TASKS_SKILL,
		"prompt": "which code should we remove for this process?",
		"context": PROPOSED,
		"calls": [_call(1, "finalize", "intent", "equals", "MIGRATION_TASKS_DRAFT")],
		# The seeded scan holds DocType names only, so naming files to delete may rerun the scan.
		"assertions": [
			IN_ORDER,
			{"assertion_type": "no_tool_call", "value": "fetch_lucidchart_document"},
			_judge(
				"Every task in migration_tasks has the category CODE REMOVAL, and no topology is proposed."
			),
		],
	},
	{
		"title": "A topology request after the tasks were drafted gets the topology",
		"skill": TOPOLOGY_SKILL,
		"prompt": "show me the topology for this process",
		"context": _context(
			"I drafted 2 tasks across 2 processes. Do they look right?",
			"MIGRATION_TASKS_DRAFT",
			topology=TOPOLOGY,
			migration_tasks=MIGRATION_TASKS,
		),
		"calls": [_call(1, "finalize", "intent", "equals", "TOPOLOGY_PROPOSAL")],
		"assertions": [IN_ORDER, NO_REFETCH],
	},
	{
		"title": "A request that names no phase is asked which one",
		"skill": TASKS_SKILL,
		"prompt": "what should we do next?",
		"context": PROPOSED,
		"calls": [_call(1, "finalize", "intent", "equals", "CLARIFY")],
		"assertions": [IN_ORDER, NO_REFETCH, {"assertion_type": "regex", "value": "(?i)topolog"}],
	},
]


def execute():
	seed_cases(CASES)
