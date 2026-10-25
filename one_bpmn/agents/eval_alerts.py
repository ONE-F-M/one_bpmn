# Copyright (c) 2026, one-fm and contributors
"""Telling the right people an eval went badly.

The scheduled sweeps used to leave a public Note. A Note is findable only by
someone who thinks to look, which is the opposite of what an overnight failure
needs — so the outcome now goes to people: whoever owns the agent that failed,
and every System Manager.

Owners first and by name, because "your agent" is the message; System Managers
because a failing agent whose owner has left, or was never set, must still
reach somebody.
"""

from __future__ import annotations

import frappe

from one_bpmn.agents.model_health import _send_email

ALERT_TYPE = "Alert"


def _is_real_user(user: str | None) -> bool:
	"""A login that can actually be told something."""
	if not user or user in ("Administrator", "Guest"):
		return False
	return bool(frappe.db.get_value("User", {"name": user, "enabled": 1}, "name"))


def owners_of(agents) -> list[str]:
	"""The process owners of these agents, in the order the agents were given."""
	owners = []
	for agent in agents or []:
		owner = frappe.db.get_value("AI Agent Configuration", agent, "process_owner")
		if _is_real_user(owner):
			owners.append(owner)
	return owners


def _agent_logins() -> set:
	"""Logins that belong to agents rather than to people.

	The platform provisions a user per agent, and those users hold System
	Manager. Alerting them means writing 36 notifications nobody will ever
	read — so they are excluded from the data that says what they are, rather
	than by guessing at their addresses.
	"""
	return {
		u for u in frappe.get_all("AI Agent Configuration", pluck="agent_user") if u
	}


def configured_recipients() -> list[str]:
	"""The Eval Alert Recipients addresses on Processa Settings, in order. An
	address that belongs to a User must be a login that can be told something."""
	addresses = frappe.utils.split_emails(frappe.db.get_single_value("Processa Settings", "eval_alert_recipients"))
	return [a for a in addresses if not frappe.db.exists("User", a) or _is_real_user(a)]


def system_managers() -> list[str]:
	"""Everyone who should hear besides the agent's owner.

	The configured list wins when there is one: on a site where service logins
	carry System Manager, "every System Manager" is a dozen alerts of which
	several go to robots.
	"""
	configured = configured_recipients()
	if configured:
		return configured

	agents = _agent_logins()
	return [
		user for user in frappe.get_all(
			"Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent"
		) if _is_real_user(user) and user not in agents
	]


def recipients_for(agents) -> list[str]:
	"""Who hears about a failure on these agents, owners first, no repeats."""
	seen, out = set(), []
	for user in list(owners_of(agents)) + system_managers():
		if user not in seen:
			seen.add(user)
			out.append(user)
	return out


def notify(subject: str, body: str, agents=None, reference_doctype: str = None,
		   reference_name: str = None) -> list[str]:
	"""Alert the owners of *agents* and the System Managers. Returns who was told.

	Never raises: a sweep that found a problem must not also fail because one
	recipient's alert could not be written — the point of the run is the finding.
	"""
	told, outside = [], []
	for user in recipients_for(agents):
		if not frappe.db.exists("User", user):
			outside.append(user)
			continue
		try:
			note = frappe.new_doc("Notification Log")
			note.for_user = user
			note.type = ALERT_TYPE
			note.subject = subject[:140]
			note.email_content = body
			if reference_doctype and reference_name:
				note.document_type = reference_doctype
				note.document_name = reference_name
			note.insert(ignore_permissions=True)
			told.append(user)
		except Exception:
			frappe.log_error(
				title="Eval alert could not be delivered",
				message=f"user={user}\n\n" + frappe.get_traceback(),
			)
	if outside:
		try:
			_send_email(outside, subject, body)
			told += outside
		except Exception:
			frappe.log_error(title="Eval alert email could not be sent", message=frappe.get_traceback())
	return told
