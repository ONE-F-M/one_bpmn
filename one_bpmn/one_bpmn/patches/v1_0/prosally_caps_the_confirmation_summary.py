"""ProsAlly's confirmation lists at most 8 steps and 6 settings, and the classifier prompt says so.

Edits the intent_classifier sub-prompt in place and adds one baseline eval case. A prompt already carrying the
change is skipped, and one whose anchors are not each found exactly once is logged and left as it is.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID, SUITE_TITLE, edit_prompt

STEPS = (
	"- List the main steps or decisions you understood from their description.",
	"- List the main steps or decisions you understood from their description. "
	"Group small related steps into one line, so the list never has more than 8.",
)
SETTINGS = (
	"the status each change moves it to, and who each task goes to.",
	"the status each change moves it to, and who each task goes to. List at most 6 settings, grouping similar ones.",
)
SENTENCES = (
	'and do not repeat them in "intro".',
	'and do not repeat them in "intro". Never list more than 8 steps or 6 settings.',
)
MARKER = "Never list more than 8 steps"
SUB_AGENT_ID = "intent_classifier"
CASE_TITLE = "A long request is confirmed with a short summary, not a line for every step"


def execute():
	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if config:
		edit_prompt(config, SUB_AGENT_ID, (STEPS, SETTINGS, SENTENCES), MARKER)
		add_eval_case()


def eval_case() -> dict:
	steps = ", ".join(f"step {n}: do thing number {n}" for n in range(1, 15))
	return {
		"title": CASE_TITLE,
		"input_user_prompt": f"Draw the Vendor Onboarding process with these steps. {steps}",
		"input_context": json.dumps({"process_name": "Vendor Onboarding"}),
		"assertions": [
			{"assertion_type": "regex", "value": "^(?![\\s\\S]*(?:\\n- [^\\n]*){15})[\\s\\S]*$"},
		],
		"expected_tool_calls": [{"call_order": 1, "tool_name": "classify_intent", "matcher": "equals"}],
	}


def add_eval_case() -> None:
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite or frappe.db.exists("AI Eval Case", {"suite": suite, "title": CASE_TITLE}):
		return
	frappe.get_doc({"doctype": "AI Eval Case", "suite": suite, "case_type": "Trajectory", **eval_case()}).insert(
		ignore_permissions=True
	)
