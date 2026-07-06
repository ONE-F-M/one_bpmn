# Copyright (c) 2026, one-fm and contributors
# WI-001423: the AI Agent Tool registry is removed — a BPMN shape is the tool.
# Drop the now-unused registry doctypes. AI Agent Tool Call (the tool-call
# child table used by AI Agent Steps) is NOT touched.

import frappe


def execute():
	for doctype in ("AI Agent Tool", "AI Agent Tool Process"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
