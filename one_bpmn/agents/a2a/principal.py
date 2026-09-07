# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Service-user provisioning for A2A Clients (WI-001931).

Every action in Frappe is performed by a user, so each approved caller
gets exactly one dedicated user carrying only the "A2A Client" role.
The user is the caller's badge: its API key authenticates the call, its
minimal role bounds what the call may touch, and disabling it is the
revocation switch. Idempotent throughout — re-approval re-enables the
same user and keeps its keys.
"""

from __future__ import annotations

import frappe

A2A_CLIENT_ROLE = "A2A Client"
CLIENT_USER_DOMAIN = "agents.internal"


def client_user_email(client_name: str) -> str:
	return f"a2a-client-{frappe.scrub(client_name)}@{CLIENT_USER_DOMAIN}"


def ensure_client_role() -> None:
	"""The minimal badge role. Desk-less; document permissions are granted
	by the add_a2a_client_role patch and the A2A doctype JSONs."""
	if frappe.db.exists("Role", A2A_CLIENT_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": A2A_CLIENT_ROLE,
			"desk_access": 0,
		}
	).insert(ignore_permissions=True)


def ensure_client_user(client) -> str:
	"""Create or re-enable the client's service user and make sure it has
	API credentials. Returns the user name (email)."""
	ensure_client_role()
	email = client_user_email(client.client_name)

	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		if not user.enabled:
			user.enabled = 1
		_ensure_role(user)
		_ensure_api_key(user)
		user.flags.ignore_permissions = True
		user.save()
		return user.name

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": f"A2A Client: {client.client_name}",
			"user_type": "System User",
			"enabled": 1,
			"send_welcome_email": 0,
			"roles": [{"role": A2A_CLIENT_ROLE}],
		}
	)
	user.flags.ignore_permissions = True
	user.flags.no_welcome_mail = True
	user.insert()
	_ensure_api_key(user)
	user.save(ignore_permissions=True)
	return user.name


def deactivate_client_user(client) -> None:
	"""Revocation switch: the key stops authenticating immediately. Keys
	are kept so a re-approval does not force the caller to reconfigure."""
	email = client.user or client_user_email(client.client_name)
	if not frappe.db.exists("User", email):
		return
	frappe.db.set_value("User", email, "enabled", 0)


def get_client_for_user(user: str | None = None) -> str | None:
	"""Resolve the session user back to its approved, enabled A2A Client
	row — the first check the A2A door makes. None means: not a client."""
	return frappe.db.get_value(
		"A2A Client",
		{"user": user or frappe.session.user, "enabled": 1, "approval_status": "Approved"},
		"name",
	)


def client_may_invoke(client_name: str, agent_configuration: str) -> bool:
	"""Positive allow-list check: is this agent on the client's list?"""
	return bool(
		frappe.db.exists(
			"A2A Client Allowed Agent",
			{
				"parent": client_name,
				"parenttype": "A2A Client",
				"agent_configuration": agent_configuration,
			},
		)
	)


def _ensure_role(user) -> None:
	if not any(r.role == A2A_CLIENT_ROLE for r in user.roles):
		user.append("roles", {"role": A2A_CLIENT_ROLE})


def _ensure_api_key(user) -> None:
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=15)
	if not user.get_password("api_secret", raise_exception=False):
		user.api_secret = frappe.generate_hash()
