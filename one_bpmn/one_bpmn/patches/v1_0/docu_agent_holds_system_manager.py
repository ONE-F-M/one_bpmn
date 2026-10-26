"""Docu creates and changes forms as its own user, so that user holds System Manager through the agent's roles."""

import frappe

from one_bpmn.agents import identity

AGENT = "Docu Agent"
ROLE = "System Manager"


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT):
		return
	doc = frappe.get_doc("AI Agent Configuration", AGENT)
	if ROLE not in {row.role for row in doc.agent_roles}:
		doc.append("agent_roles", {"role": ROLE})
		doc.save(ignore_permissions=True)
	email = identity.ensure_agent_user(doc)
	if email and doc.get("agent_user") != email:
		doc.db_set("agent_user", email, update_modified=False)
