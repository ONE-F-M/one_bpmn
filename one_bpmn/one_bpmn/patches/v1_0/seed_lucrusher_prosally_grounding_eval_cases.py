"""LuCrusher Baseline gains five cases for ProsAlly prompts grounded in the code and the Workflow.

Each starts from confirmed migration tasks and asks for the prompts; the model reads the code
with read_doctype_logic and the judge checks the drafted blocks. Idempotent by suite and case title.
"""

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import (
	DOC_SUMMARY,
	IN_ORDER,
	LUCID_DOC_ID,
	PARSED_DOC,
	SCAN_SUMMARY,
	_call,
	_judge,
	_state,
)
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skill_eval_cases import NO_REFETCH, _turn, seed_cases
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL

PROMPT = "now write the ProsAlly prompts"
BOT_TEXT = "Migration tasks confirmed. Next I can write the ProsAlly prompts."
READ_THEN_DRAFT = [
	_call(1, "read_doctype_logic"),
	_call(2, "finalize", "intent", "equals", "PROSALLY_PROMPT_DRAFT"),
]


def _case(title, topology_names, rubric, lucid=None):
	topology = {
		"total_processes": len(topology_names),
		"processes": [{"process_name": name} for name in topology_names],
	}
	tasks = {
		"processes": [
			{
				"process_name": name,
				"tasks": [{"category": "PROCESS MAP", "task": f"Build the {name} map", "references": ["code"]}],
			}
			for name in topology_names
		]
	}
	state = _state(
		"MIGRATION_TASKS_CONFIRMED",
		document=DOC_SUMMARY,
		codebase_scan=SCAN_SUMMARY,
		topology=topology,
		migration_tasks=tasks,
	)
	context = _turn("approved", BOT_TEXT, state)
	context["session_state"] = {f"lucid_doc:{LUCID_DOC_ID}": {**PARSED_DOC, **(lucid or {})}}
	return {
		"title": title,
		"skill": PROSALLY_SKILL,
		"prompt": PROMPT,
		"context": context,
		"calls": READ_THEN_DRAFT,
		"assertions": [IN_ORDER, NO_REFETCH, _judge(rubric)],
	}


CASES = [
	_case(
		"Event Staff blocks cite the approval wait, same-day deletion and roster conflict",
		["Schedule Event Staff"],
		"The Event Staff blocks have an element that waits for the Client Event to be Approved before "
		"schedules are generated, an element for deleting a schedule on the same day, and an element "
		"that rejects an Over-Time schedule overlapping a Basic one. Each of these elements names the "
		"method it comes from as src=<file>:<method>.",
	),
	_case(
		"Lanes come from the Workflow roles, not the Lucidchart lanes",
		["Approve Client Event"],
		"The lanes of the Client Event block are exactly Operations Supervisor, Project Manager and "
		"Operations Manager. There is no Event Creator lane, and the reply or the conflicts list says "
		"the Lucidchart lane Event Creator matches no Workflow role.",
		lucid={"swimlanes": ["Event Creator", "Operations Supervisor", "Project Manager", "Operations Manager"]},
	),
	_case(
		"Preventive Maintenance blocks loop per task and split the SLA",
		["Generate Maintenance Schedule", "Complete Maintenance Work Order"],
		"The schedule block loops once per checklist task, not one straight line. It reads both the "
		"schedule generation months and the work order generation lead time days from Maintenance "
		"Settings and names both fields. The work order block carries the full location chain, not "
		"only space and object, and has a reactive SLA step separate from the preventive SLA step.",
	),
	_case(
		"A Lucidchart and code disagreement is listed and asked, not chosen",
		["Generate Maintenance Schedule"],
		"The reply lists the conflict about the schedule base date: Lucidchart says Last Service, then "
		"Commissioning, then Creation, while the code uses Last Service Date or today. It asks the user "
		"which is right, and the finalize conflicts list holds that entry with a citation.",
		lucid={"steps": ["Base date for the schedule: Last Service, else Commissioning, else Creation"]},
	),
	_case(
		"Four processes are drafted two at a time",
		["Request Visa", "Approve Visa", "Renew Visa", "Cancel Visa"],
		"The prosally_prompts holds at most two processes, remaining names the other processes not yet "
		"drafted, no prompt_block has more than 25 elements in section C, and the reply tells the user "
		"to say continue for the rest.",
	),
]


def execute():
	seed_cases(CASES)
