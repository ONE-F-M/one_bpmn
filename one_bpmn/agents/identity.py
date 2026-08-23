# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""An identity of an agent's own (WI-002054).

Until now an agent had no user. Its tools ran as whatever user the worker session
happened to be, so every write an agent made was recorded against a person —
usually Administrator, sometimes whoever started the run — and was permitted or
refused by that person's roles rather than by anything anyone had decided about
the agent. Two consequences, and the second is the worse one:

- **Nothing was attributable.** The Version row, the workflow comment and the
  audit trail all named a human for a change no human made.
- **Nothing was grantable.** "May this agent move a work item to Done" had no
  answer you could set, because there was no subject to grant it to. Widening or
  narrowing what an agent may do meant editing code.

So each agent gets a User, and its tools run as that User with permissions on.
What an agent may do is then a list of roles on its configuration: add one to
grant, remove one to revoke, no deployment either way.

WHY THE USER IS ENABLED
-----------------------
It has to be. ``frappe.set_user`` refuses a disabled user, and a disabled user
cannot own a write — so an identity that cannot be switched to is not an identity.
What keeps a person out of it instead: no password is ever set, it is created with
no welcome email, it is kept out of mention lists, and its API access is not
issued. It is a subject for permissions, not an account for a human, and the
description on the field says so.
"""

from __future__ import annotations

import frappe
from frappe import _

# The domain agent users live on. A real-looking address would invite somebody to
# send it an email; this one cannot receive anything and reads as what it is.
AGENT_EMAIL_DOMAIN = "agents.processa.invalid"


def agent_email(agent_configuration: str) -> str:
	"""A stable, obviously-not-a-person address derived from the agent's name.

	Derived rather than stored so it survives a configuration being renamed and
	re-provisioned, and scrubbed because an agent name may carry spaces and
	punctuation that an email local part may not.
	"""
	return f"{frappe.scrub(agent_configuration)}@{AGENT_EMAIL_DOMAIN}"


def ensure_agent_user(doc) -> str | None:
	"""Give this agent its identity, and make its roles match its configuration.

	Never raises: an agent whose user could not be provisioned is an agent whose
	tools fall back to running as the session user — worse attributed, not
	broken — and refusing to save a configuration because of it would be a
	strange way to find out.
	"""
	try:
		email = agent_email(doc.name)
		if not frappe.db.exists("User", email):
			user = frappe.new_doc("User")
			user.update({
				"email": email,
				"first_name": doc.get("agent_name") or doc.name,
				"last_name": "(agent)",
				# System User because roles only mean anything on one, and roles
				# are the entire point of this identity.
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
				# Kept out of the places a person picks a colleague from.
				"allowed_in_mentions": 0,
				"document_follow_notify": 0,
				"thread_notify": 0,
			})
			user.flags.ignore_permissions = True
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)
		sync_roles(doc, email)
		return email
	except Exception:
		frappe.log_error(
			title=f"Agent identity: could not provision a user for {doc.name}",
			message=frappe.get_traceback(),
		)
		return None


def sync_roles(doc, email: str) -> list:
	"""The agent's user holds EXACTLY the roles its configuration names.

	Exactly, not at least: removing a role from the configuration has to revoke
	it, or the list stops being the answer to "what may this agent do" and
	becomes a record of what it was once allowed. Roles a person granted by hand
	are removed too, for the same reason — the configuration is the source, and
	two sources disagree the moment either changes.
	"""
	wanted = {
		row.role
		for row in (doc.get("agent_roles") or [])
		if row.role and frappe.db.exists("Role", row.role)
	}
	user = frappe.get_doc("User", email)
	# "All" and the desk role arrive by themselves and are not ours to manage.
	managed = {r.role for r in user.get("roles") or []} - {"All", "Guest"}
	if managed == wanted:
		return sorted(wanted)

	user.set("roles", [])
	for role in sorted(wanted):
		user.append("roles", {"role": role})
	user.flags.ignore_permissions = True
	user.save(ignore_permissions=True)
	return sorted(wanted)


def user_for(agent_configuration: str | None) -> str | None:
	"""The identity to run an agent's tools as, or None to leave it alone.

	None is a real answer and not a failure: a tool called outside any agent, or
	by an agent provisioned before this existed, should run exactly as it did
	before rather than as somebody arbitrary.
	"""
	if not agent_configuration:
		return None
	email = frappe.db.get_value("AI Agent Configuration", agent_configuration, "agent_user")
	if email and frappe.db.exists("User", email):
		return email
	# Not provisioned yet — derive it, but only claim it if it actually exists.
	derived = agent_email(agent_configuration)
	return derived if frappe.db.exists("User", derived) else None


def describe_refusal(agent_configuration: str | None, error: Exception) -> str:
	"""Turn a permission failure into something the MODEL can act on.

	A bare "PermissionError" tells the agent nothing, and WI-002053 showed twice
	over what happens then: it reports the work as done, or blames something
	transient and offers to retry. Naming the identity and the fact that this is
	configuration rather than bad luck is what stops both.
	"""
	roles = []
	if agent_configuration:
		roles = [
			r.role
			for r in frappe.get_all(
				"AI Agent Allowed Role",
				filters={"parent": agent_configuration, "parentfield": "agent_roles"},
				fields=["role"],
			)
		]
	return _(
		"Refused: {0} is not permitted to do that. It acts as its own user and holds "
		"{1}. This is a permission that has to be granted on the agent's configuration — "
		"it will be refused the same way every time until it is, so do not retry it. Say "
		"what you could not do and why."
	).format(
		agent_configuration or _("this agent"),
		_("these roles: {0}").format(", ".join(roles)) if roles else _("no roles at all"),
	)
