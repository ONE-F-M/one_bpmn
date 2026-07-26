"""
WI-001613: Move the agent + chat doctypes from onefm_mcp into one_bpmn.

Runs pre_model_sync so the module is reassigned BEFORE doctype sync: the
doctype JSON files now live under one_bpmn, and if the DocType rows still
said "ONEFM MCP" when migrate's orphan cleanup ran, the doctypes would be
treated as removed from their app and deleted. Table names are unchanged,
so no data moves.
"""

import frappe

DOCTYPES = [
	"AI Agent Configuration",
	"AI Agent Sub Prompt",
	"AI Agent Constant",
	"Chat Conversation",
	"Chat Message",
	"Chat Participant",
	"AI Model",
]


def execute():
	for name in DOCTYPES:
		if not frappe.db.exists("DocType", name):
			continue  # fresh install — sync will create it under one_bpmn
		current = frappe.db.get_value("DocType", name, "module")
		if current == "ONE BPMN":
			continue  # already moved
		frappe.db.set_value("DocType", name, "module", "ONE BPMN", update_modified=False)

	frappe.clear_cache()
