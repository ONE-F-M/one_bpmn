# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002054: give every existing agent the identity it now acts as.

New agents get one on save. The ones already on a site would not, until somebody
happened to re-save them — and an agent with no user falls back to running its
tools as whatever the session user is, which is exactly the behaviour this story
exists to end. So they are provisioned here.

Deliberately granting NO roles. An agent that could suddenly write more than it
could yesterday, because a patch decided so, is the wrong kind of surprise —
every one of these has been running with borrowed permissions, and the right
place to decide what it should actually have is its configuration, in front of
somebody. Until a role is added the identity is inert: attributable, and
permitted nothing.
"""

import frappe


def execute():
	if not frappe.db.has_column("AI Agent Configuration", "agent_user"):
		return

	from one_bpmn.agents import identity

	provisioned, already, failed = 0, 0, 0
	for name in frappe.get_all("AI Agent Configuration", pluck="name"):
		try:
			doc = frappe.get_doc("AI Agent Configuration", name)
			if doc.get("agent_user") and frappe.db.exists("User", doc.agent_user):
				already += 1
				continue
			email = identity.ensure_agent_user(doc)
			if email:
				frappe.db.set_value(
					"AI Agent Configuration", name, "agent_user", email, update_modified=False
				)
				provisioned += 1
			else:
				failed += 1
		except Exception:
			failed += 1
			frappe.log_error(
				title=f"Agent identity patch: {name}", message=frappe.get_traceback()
			)

	frappe.db.commit()
	print(
		f"Agent identities: {provisioned} provisioned, {already} already had one, {failed} failed"
	)
