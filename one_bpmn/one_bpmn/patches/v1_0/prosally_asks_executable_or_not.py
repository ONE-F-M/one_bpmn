"""ProsAlly asks whether to draw a new or redrawn process as executable or non-executable.

Replaces the classifier bullet that decided the kind itself: an unanswered kind is now INCOMPLETE, the clarifier
asks it with two options, and the confirmation names the kind the person chose. Prompts already changed are skipped.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_confirms_executable_or_not import (
	CASES,
	CLASSIFIER_ANCHOR,
	CLASSIFIER_NEW,
	add_eval_case,
)
from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID, edit_prompt

CLASSIFIER_MARKER = "has not chosen whether"
CLARIFIER_MARKER = "Should I draw it as an executable process"

QUESTION = (
	"Should I draw it as an executable process (one the system runs) "
	"or a non-executable process (a guide people follow)?"
)

INCOMPLETE_ANCHOR = "- INCOMPLETE applies when the action type is clear but there is not enough detail to carry it out.\n"
INCOMPLETE_NEW = (
	INCOMPLETE_ANCHOR
	+ "- For GENERATE_NEW and OVERWRITE_EXISTING the person must say whether the process is executable (the system runs it) "
	"or non-executable (a guide people follow). It counts as said when the request, or an earlier reply in the "
	"conversation, says so, including a one-word reply to that question. When the person has not chosen whether, "
	"classify as INCOMPLETE and write in reason: needs the kind of process, executable or non-executable. "
	"This holds even when skip_confirmation would be true.\n"
)

CONFIRMATION_NEW = (
	'- For GENERATE_NEW and OVERWRITE_EXISTING, say in "intro" which kind the person chose. '
	'Say "I\'ll set it up as an executable process, one the system runs" or '
	'"I\'ll set it up as a non-executable process, a guide people follow".\n' + CLASSIFIER_ANCHOR
)

CLARIFIER_ANCHOR = "- Do NOT use words like BPMN, flow, element, event, gateway, modelling, or XML.\n"
CLARIFIER_NEW = (
	CLARIFIER_ANCHOR
	+ '- When the classification reason says the kind of process is needed, ask exactly: "'
	+ QUESTION
	+ '" with the options "Executable" and "Non-executable".\n'
)

EVAL_PROMPTS = {
	"A timer-driven job is confirmed as executable": (
		"Draw the Sending Fingerprint Appointment Reminders process as an executable process. "
		"Every day at 9am it finds the day's fingerprint appointments and emails each applicant a reminder."
	),
	"A record creation guide is confirmed as non-executable": (
		"Draw the Item Creation process as a non-executable process. "
		"The storekeeper opens a new Item, fills in the item details and saves it."
	),
}

NEW_CASES = (
	{
		"title": "A new process without a stated kind gets the executable question",
		"input_user_prompt": "Draw the Item Creation process. The storekeeper opens a new Item, fills in the item details and saves it.",
		"regex": '(?i)"intent"\\s*:\\s*"INCOMPLETE"',
	},
	{
		"title": "A request that states its kind is confirmed without the question",
		"input_user_prompt": "Draw the Item Creation process as a non-executable process. The storekeeper opens a new Item and saves it.",
		"regex": '(?i)"intent"\\s*:\\s*"GENERATE_NEW"',
	},
)


def execute():
	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not config:
		return
	edit_prompt(
		config,
		"intent_classifier",
		((CLASSIFIER_NEW, CONFIRMATION_NEW), (INCOMPLETE_ANCHOR, INCOMPLETE_NEW)),
		CLASSIFIER_MARKER,
	)
	edit_prompt(config, "clarifier", ((CLARIFIER_ANCHOR, CLARIFIER_NEW),), CLARIFIER_MARKER)
	update_eval_cases()
	for case in NEW_CASES:
		add_eval_case(case)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def update_eval_cases() -> None:
	"""The two earlier cases name their kind in the request, so the question is not asked."""
	for case in CASES:
		name = frappe.db.get_value("AI Eval Case", {"title": case["title"]}, "name")
		if name:
			frappe.db.set_value("AI Eval Case", name, "input_user_prompt", EVAL_PROMPTS[case["title"]])
