"""Let the coding agents read the Work Item they are working on.

A specialist used to start from the delegator's summary alone; read_work_item
lets it read the record, but only as its own identity — and until now three of
the four had a user with no roles and the Dev Agent had no user at all.
Developer already holds Work Item read, so that is the role each gets.
"""

import frappe

from one_bpmn.agents import identity

AGENTS = ("Dev Agent", "Frontend Agent", "Mobile App Agent", "Connector Agent")
ROLE = "Developer"


def execute():
	if not frappe.db.exists("Role", ROLE):
		return
	for agent in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", agent):
			continue
		doc = frappe.get_doc("AI Agent Configuration", agent)
		if ROLE not in {row.role for row in doc.get("agent_roles") or []}:
			doc.append("agent_roles", {"role": ROLE})
			doc.save(ignore_permissions=True)
		email = identity.ensure_agent_user(doc)
		if email and doc.get("agent_user") != email:
			doc.db_set("agent_user", email, update_modified=False)
