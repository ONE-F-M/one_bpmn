"""
Who may see which AI Memory rows.

Wired into Frappe's ``permission_query_conditions`` and ``has_permission``
hooks, so the rule is enforced once and applies everywhere a memory is read:
the Processa memory browser, the Desk list, a report, an API call. The
alternative was scoping by hand in each endpoint with ``ignore_permissions``,
which is the arrangement that lets one forgotten call site leak a person's
memories.

The rule, in one line: your own memories plus the shared ones, and a System
Manager sees everybody's.

"Shared" is a row with no user. Those belong to the agent and to everyone who
uses it, which is what an Agent-scoped memory has always been. Only rows
written under one of the User scopes carry a user, and those are private to
that person.

Note this governs READING. The trusted dispatch path does its own scoping with
``ignore_permissions=True`` and an explicit user key, because it runs as the
system for an agent turn and must not depend on the requesting user's Desk
permissions.
"""

from __future__ import annotations

import frappe


def is_system_manager(user: str | None = None) -> bool:
	return "System Manager" in frappe.get_roles(user or frappe.session.user)


def ai_memory_query_conditions(user: str | None = None) -> str:
	"""SQL fragment limiting a memory listing to what ``user`` may read.

	``IFNULL(user, '')`` because a shared row may hold NULL (written before the
	user field existed) or the empty string (written since), and both mean the
	same thing.
	"""
	user = user or frappe.session.user
	if is_system_manager(user):
		return ""
	return (
		"(IFNULL(`tabAI Memory`.`user`, '') = ''"
		f" OR `tabAI Memory`.`user` = {frappe.db.escape(user)})"
	)


# Changing a memory is not the same as reading one. A shared memory belongs to
# the agent and to everybody using it, so one person retiring it would take it
# away from the whole team.
_CHANGING = ("write", "create", "delete", "submit", "cancel", "amend")


def ai_memory_has_permission(doc, ptype=None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_system_manager(user):
		return True
	owner = getattr(doc, "user", None) or ""
	if ptype in _CHANGING:
		return bool(owner) and owner == user
	return owner in ("", user)
