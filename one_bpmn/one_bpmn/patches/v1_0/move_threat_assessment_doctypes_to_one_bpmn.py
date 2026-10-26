"""
WI-002201: Move the Threat Assessment Report doctypes from onefm_mcp into one_bpmn.

Runs pre_model_sync so the module is reassigned BEFORE doctype sync: the
doctype JSON files now live under one_bpmn, and if the DocType rows still
said "ONEFM MCP"/"onefm_mcp" when migrate's orphan cleanup ran, the doctypes
would be treated as removed from their app and deleted. Table names are
unchanged, so no data moves. Mirrors move_agent_chat_doctypes_to_one_bpmn
(WI-001613) and move_threat_intel_doctypes_to_one_bpmn (WI-002203) — the
sibling patch moving the Threat Source Discovery doctypes on the same day.

This is the doctype-relocation half only. The SITREP/report generation logic
itself (currently onefm_mcp's threat_assessment_agent LangGraph pipeline)
stays live and unmodified in onefm_mcp until its replacement BPMN Process
Model is built and validated in the Processa editor — see
onefm_mcp/DEPRECATION_PLAN.md and the WI-002201 implementation plan for the
target design and cutover sequencing.
"""

import frappe

DOCTYPES = [
	"Threat Assessment Report",
	"Threat Assessment Security Threat",
	"Threat Assessment Environmental Threat",
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
