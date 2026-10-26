"""ProsAlly's go-ahead message comes back as an intro, the steps and the settings, which join_confirmation lays out.

Edits the classifier and confirmer prompts in place once; a prompt whose anchor moved is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

AGENT_ID = "prosally_agent"

PARTS_RULE = (
	'- Put what you will do in "intro", in one or two sentences. Put each step or decision you understood in '
	'"steps" and each setting in "settings", one short plain sentence each, and do not repeat them in "intro". '
	'Leave "settings" empty when there are none; the "draw only" offer is added for you, so "question" '
	'stays a short yes/no question such as "Shall I go ahead?".\n'
)
PARTS_JSON = (
	'"summary": {"intro": "what you will do, in one or two sentences", '
	'"steps": ["each step or decision you understood"], "settings": ["each setting you would put on the steps"]}'
)

EDITS = {
	"intent_classifier": (
		(
			'and who each task goes to. Then tell them they can reply "draw only" to get the steps without these settings.\n',
			"and who each task goes to.\n",
		),
		("- Keep it short, 2 to 4 sentences plus a brief list.\n", PARTS_RULE),
		('"summary": "the confirmation message described above, or empty"', PARTS_JSON + " or empty"),
	),
	"confirmer": (
		("- Keep it short \u2014 2 to 4 sentences plus a brief list.\n", PARTS_RULE),
		('{"summary": "plain-English summary of what you will do and what you understood", ', "{" + PARTS_JSON + ", "),
	),
}


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	config = frappe.get_doc("AI Agent Configuration", name)
	changed = False
	for row in config.sub_prompts:
		text = row.prompt_text
		for anchor, replacement in EDITS.get(row.sub_agent_id, ()):
			text = apply_edit(text, anchor, replacement) if text is not None else None
		if text is None:
			frappe.log_error(
				title="prosally_confirmation_in_parts: prompt anchor not found",
				message=f"The {row.sub_agent_id} prompt does not carry each anchor exactly once; it is left as it is.",
			)
		elif text != row.prompt_text:
			row.prompt_text = text
			changed = True
	if changed:
		config.save(ignore_permissions=True)
