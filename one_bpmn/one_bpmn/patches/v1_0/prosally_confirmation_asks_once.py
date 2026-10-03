"""ProsAlly's confirmation asks its yes/no question once.

The confirmer and intent classifier prompts keep the question out of the summary, and the Confirm and
Classify Intent scripts join the two with join_confirmation, which drops a closing summary sentence
that repeats the question. A script already calling it is skipped, and one whose anchors are not each
found exactly once is logged and left as it is.
"""

import frappe

AGENT_ID = "prosally_agent"
# Matched with like to avoid the dash in the Server Script names.
SCRIPTS = ("ProsAlly%Tool Confirm", "ProsAlly%Tool Classify Intent")
IMPORT_OLD = "from one_bpmn.agents.prosally_helpers import complete_sub_prompt, "
IMPORT_NEW = "from one_bpmn.agents.prosally_helpers import complete_sub_prompt, join_confirmation, "
JOIN_OLD = 'response_text = (summary + "\\n" + question) if summary else question'
JOIN_NEW = "response_text = join_confirmation(summary, question)"

QUESTION_RULE = '- Do not ask a question in the summary: it says what you will do, and the yes/no question goes only in "question".'
# Sub-prompt id -> the rule it carries today that puts the question inside the summary.
PROMPT_RULES = {
	"confirmer": '- End with a simple yes/no question like "Shall I go ahead?"',
	"intent_classifier": '- End with a simple yes/no question such as "Shall I go ahead?"',
}


def execute():
	for pattern in SCRIPTS:
		_update_script(pattern)
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	for sub_agent_id, old_rule in PROMPT_RULES.items():
		row = frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": name, "sub_agent_id": sub_agent_id}, ["name", "prompt_text"]
		)
		if row and (row[1] or "").count(old_rule) == 1:
			frappe.db.set_value(
				"AI Agent Sub Prompt", row[0], "prompt_text", row[1].replace(old_rule, QUESTION_RULE)
			)


def _update_script(pattern: str):
	name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
	if not name:
		return
	doc = frappe.get_doc("Server Script", name)
	if JOIN_NEW in doc.script:
		return
	script = with_join_confirmation(doc.script)
	if script is None:
		frappe.log_error(
			title="prosally_confirmation_asks_once: anchors not found",
			message=f"{name} does not carry each anchor exactly once; the script is left as it is.",
		)
		return
	doc.script = script
	doc.save(ignore_permissions=True)


def with_join_confirmation(script: str) -> str | None:
	"""The script joining summary and question with join_confirmation, or None if an anchor moved."""
	if script.count(IMPORT_OLD) != 1:
		return None
	if script.count(JOIN_OLD) != 1:
		return None
	return script.replace(IMPORT_OLD, IMPORT_NEW, 1).replace(JOIN_OLD, JOIN_NEW, 1)
