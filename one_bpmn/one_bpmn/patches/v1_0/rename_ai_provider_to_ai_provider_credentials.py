"""
WI-001626: Rename the AI Provider doctype to AI Provider Credentials.

AI Provider Credentials is the single store of LLM credentials for all
agents (see WI-001615 — per-agent overrides are removed). frappe.rename_doc
renames the table and updates DB-stored Link/Select references; app-bundled
JSON references are updated in this same commit.
"""

import frappe


def execute():
	if frappe.db.exists("DocType", "AI Provider Credentials"):
		return  # already renamed (fresh install ships the new name)

	if not frappe.db.exists("DocType", "AI Provider"):
		return  # never installed — nothing to rename

	frappe.rename_doc("DocType", "AI Provider", "AI Provider Credentials", force=True)
	frappe.reload_doc("one_bpmn", "doctype", "ai_provider_credentials")
