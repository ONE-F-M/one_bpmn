"""
WI-002202: Move the Threat Feed Collection doctypes from onefm_mcp into one_bpmn.

Runs pre_model_sync so the module is reassigned BEFORE doctype sync: the
doctype JSON files now live under one_bpmn, and if the DocType rows still
said "ONEFM MCP" when migrate's orphan cleanup ran, the doctypes would be
treated as removed from their app and deleted. Table names are unchanged,
so no data moves. Mirrors move_threat_intel_doctypes_to_one_bpmn (WI-002203,
Agent 1's sibling move) and move_agent_chat_doctypes_to_one_bpmn (WI-001613).
"""

import frappe

DOCTYPES = [
	"Threat Feed",
	"Threat Feed Keyword",
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
