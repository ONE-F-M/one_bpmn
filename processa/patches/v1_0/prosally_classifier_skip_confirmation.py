"""ProsAlly's intent classifier reports skip_confirmation when the person says to act without asking first.

Each edit fires only while its anchor is present and its new text is not.
"""

import frappe

AGENT_ID = "prosally_agent"
SUB_AGENT_ID = "intent_classifier"

RULE_ANCHOR = "- Anything outside process modelling scope is IRRELEVANT.\n"
RULE = (
	"- skip_confirmation is true only when the user explicitly says to act without being asked first, "
	'for example "draw it now, don\'t ask", "no need to confirm", or "just do it without checking with me". '
	"A plain request to draw or change something is not such an instruction, so skip_confirmation is false. "
	"It is always false for AMBIGUOUS, INCOMPLETE, and IRRELEVANT.\n"
)
SHAPE_OLD = '"question": "the yes/no question, or empty"}'
SHAPE_NEW = '"question": "the yes/no question, or empty", "skip_confirmation": true or false}'


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Agent Configuration", name)
	updated = False
	for row in doc.sub_prompts:
		if row.sub_agent_id != SUB_AGENT_ID:
			continue
		text = row.prompt_text or ""
		if RULE not in text and RULE_ANCHOR in text:
			text = text.replace(RULE_ANCHOR, RULE_ANCHOR + RULE, 1)
		if SHAPE_NEW not in text and SHAPE_OLD in text:
			text = text.replace(SHAPE_OLD, SHAPE_NEW, 1)
		if text != (row.prompt_text or ""):
			row.prompt_text = text
			updated = True
	if updated:
		doc.save(ignore_permissions=True)
