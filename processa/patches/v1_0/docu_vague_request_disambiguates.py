"""Docu's classifier asks what a form is for instead of designing one from nothing."""

import frappe

AGENT_ID = "docu_agent"
ANCHOR = "or when the request is too vague to act on.\n"
RULE = (
	'- A request that says neither what the DocType is for nor anything it should record ("a form for '
	'my team", "I need a doctype") is DISAMBIGUATE, never CREATE.\n'
)


def execute():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not agent:
		return
	row = frappe.db.get_value(
		"AI Agent Sub Prompt",
		{"parent": agent, "sub_agent_id": "intent_classifier"},
		["name", "prompt_text"],
		as_dict=True,
	)
	text = (row or {}).get("prompt_text") or ""
	if RULE in text or ANCHOR not in text:
		return
	frappe.db.set_value("AI Agent Sub Prompt", row.name, "prompt_text", text.replace(ANCHOR, ANCHOR + RULE, 1))
