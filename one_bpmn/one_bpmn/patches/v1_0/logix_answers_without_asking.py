"""Logix answers a question about the linked script without asking one back.

The writer's QUESTIONS rule gains a sentence saying not to ask, and the baseline question case carries a
fixture whose names and message agree. Each edit applies once; a prompt without the anchor is logged and
left as it is.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_baseline_suite as seed
from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

WRITER_AGENT_ID = "logix_script_writer"
QUESTION_CASE = "A question about the linked script is answered with no code change"
ANCHOR = "Do not rewrite the script."
RULE = (
	" Do not ask the person anything back. If a name or a field in the script looks inconsistent, "
	"say so in one sentence instead of asking which they mean."
)


def execute():
	_edit_prompt()
	_refresh_question_fixture()


def _edit_prompt():
	name, prompt = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": WRITER_AGENT_ID}, ["name", "system_prompt"]
	) or (None, None)
	if not name:
		return
	edited = apply_edit(prompt or "", ANCHOR, ANCHOR + RULE)
	if edited is None:
		frappe.log_error(
			title="logix_answers_without_asking: anchor not found",
			message=f"{name} has no single '{ANCHOR}' line; the prompt is left as it is.",
		)
		return
	if edited != prompt:
		frappe.db.set_value("AI Agent Configuration", name, "system_prompt", edited)
		frappe.cache.delete_value(f"agent_config:{WRITER_AGENT_ID}")


def _refresh_question_fixture():
	suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name")
	case = suite and frappe.db.get_value("AI Eval Case", {"suite": suite, "title": QUESTION_CASE}, "name")
	if not case:
		return
	context = next(c["context"] for c in seed.CASES if c["title"] == QUESTION_CASE)
	frappe.db.set_value("AI Eval Case", case, "input_context", json.dumps(context))
