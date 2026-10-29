"""ProsAlly decides whether a process is executable and confirms it before drawing.

Seeds the onefm-bpm-approach-reference skill, tells the classifier to name the kind in its confirmation, and
tells the generator to set the IR "executable" flag from it. Prompts already carrying the change are skipped.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID, SUITE_TITLE, edit_prompt
from one_bpmn.one_bpmn.patches.v1_0.seed_prosally_and_frontend_skills import (
	PROSALLY_CONFIG_NAME,
	_enable_skill,
	_upsert_skill,
)

SKILL = "onefm-bpm-approach-reference"
CLASSIFIER_MARKER = "a guide people follow"

SKILL_DESCRIPTION = (
	"The OneFM BPM approach for telling an executable process from a non-executable one: process groups, "
	"creation and screen-driven guides, DocType lifecycles, scheduled, action-triggered and AI Agent processes. "
	"Use this skill before drawing a process, to choose and confirm its kind. Do NOT use it for a change to an existing diagram."
)

SKILL_BODY = """# OneFM BPM approach: what is executable and what is not

Decide the kind of process first. Executable processes are deployed and run by the Processa engine. Non-executable processes are instructions or overviews: they are drawn, never deployed.

## Non-executable
1. **Process group** - a level where related processes are grouped in a folder. The model shows how the processes relate, not how each runs. Draw each process as a call activity and link them. Examples: Support Functions, Human Capital Management, Government Relations, Attendance Management, Shift Request.
2. **Creating or initiating something** - instructions to get an outcome, usually a new record created by a person (not by a script, another process or a timer). Examples: Annual Leave Application Creation, Timesheet Creation, Item Creation, Warehouse Creation, Journal Entry Creation.
3. **Frontend-driven activity** - instructions to get an outcome by working in the screen, with or without creating or updating records. Examples: Rostering an Employee to a basic shift, Rostering an Employee to a specific type of overtime shift, Assigning Day(s) Off to Employee(s), Creating a Route Plan on the Transportation Schedule, Reassigning Vehicle to a Trip.

## Executable
4. **Lifecycle of a DocType** - triggered by the creation of a new document (sometimes with an extra condition). It ends at the happy path, though other end events such as rejection can exist. Examples: Journal Entry Lifecycle, Timesheet Lifecycle, Request for Material Lifecycle, Bulk Hiring ERF Lifecycle, A La Carte ERF Lifecycle.
5. **Schedule-based** - the trigger is a timer event that fires on a cycle. Examples: Marking Shift-based Attendance (hourly), Marking General Attendance (daily 12:45pm), Sending Fingerprint Appointment Reminders (daily 9am), Syncing Google Tasks with ERPNext ToDos (every 5 minutes).
6. **Action-triggered** - the engine starts the process on a message sent by an action. Examples: Journal Entry Cancellation, Syncing Google Task to ERPNext (Sync My Google Task button), RFM Cancellation, Job Offer Revocation, Leave Cancellation.
7. **AI Agent** - every AI Agent has a process that defines how it is triggered and what it can do. Executable.

## How to apply
- Match the request to the closest kind above. A name ending in "Creation" is usually kind 2, "Lifecycle" kind 4, "Cancellation" or "Revocation" kind 6, a recurring job kind 5, a folder of processes kind 1.
- Say the kind in the confirmation and let the person correct it before drawing. If two kinds fit, name both and ask which.
- Set the IR flag to match: `"executable": false` for kinds 1 to 3, omit it (executable) for kinds 4 to 7.
"""

CLASSIFIER_ANCHOR = "- Only name a record the person mentioned."
CLASSIFIER_NEW = (
	'- For GENERATE_NEW and OVERWRITE_EXISTING, say in "intro" which kind of process this is, so the person can correct you. '
	'Say "I\'ll set it up as an executable process, one the system runs" for the life of a record from creation to its end, '
	"a process started by a schedule or timer, or one started by an action such as a cancel or a button. "
	'Say "I\'ll set it up as a non-executable process, a guide people follow" for a group of related processes shown as one overview, '
	"how a person creates or starts a record, or how a person does a task on screen such as rostering or assigning days off. "
	"When it fits neither, pick the closer one and say why in a few words.\n" + CLASSIFIER_ANCHOR
)

GENERATOR_ANCHOR = "=== IR SCHEMA ===\n"
GENERATOR_NEW = (
	"=== EXECUTABLE OR NOT ===\n\n"
	f'Load the {SKILL} skill. Put "executable": false at the top of the IR, next to "name", when the confirmation said '
	"a guide people follow (process group, creating something, a task done on screen). Leave it out when the process "
	"is one the system runs. When the confirmation did not say, decide from the skill.\n\n" + GENERATOR_ANCHOR
)

CASES = (
	{
		"title": "A timer-driven job is confirmed as executable",
		"input_user_prompt": "Draw the Sending Fingerprint Appointment Reminders process. Every day at 9am it finds the day's appointments and emails each applicant.",
		"regex": "(?i)(?<!non-)executable",
	},
	{
		"title": "A record creation guide is confirmed as non-executable",
		"input_user_prompt": "Draw the Item Creation process. The storekeeper opens a new Item, fills in the details and saves it.",
		"regex": "(?i)non-executable",
	},
)


def execute():
	_upsert_skill({"skill_name": SKILL, "description": SKILL_DESCRIPTION, "body": SKILL_BODY})
	if frappe.db.exists("AI Agent Configuration", PROSALLY_CONFIG_NAME):
		_enable_skill(PROSALLY_CONFIG_NAME, SKILL)
	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not config:
		return
	edit_prompt(config, "intent_classifier", ((CLASSIFIER_ANCHOR, CLASSIFIER_NEW),), CLASSIFIER_MARKER)
	edit_prompt(config, "process_generator", ((GENERATOR_ANCHOR, GENERATOR_NEW),), SKILL)
	for case in CASES:
		add_eval_case(case)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def add_eval_case(case: dict) -> None:
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite or frappe.db.exists("AI Eval Case", {"suite": suite, "title": case["title"]}):
		return
	frappe.get_doc({
		"doctype": "AI Eval Case",
		"suite": suite,
		"case_type": "Trajectory",
		"title": case["title"],
		"input_user_prompt": case["input_user_prompt"],
		"input_context": json.dumps({}),
		"assertions": [{"assertion_type": "regex", "value": case["regex"]}],
		"expected_tool_calls": [{"call_order": 1, "tool_name": "classify_intent", "matcher": "equals"}],
	}).insert(ignore_permissions=True)
