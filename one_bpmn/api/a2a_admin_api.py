# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Admin surface for the A2A operation (WI-001934).

Two registries and one monitor, so external collaboration is governed
without the Desk:

- **remote agents** (outbound) — who we may delegate to
- **clients** (inbound) — who may call us, and which agents they reach
- **tasks** — what is in flight in either direction, with the delegation
  counters and deadlines that decide when it stops

Read-mostly. Every write calls the module that owns the behaviour — the
doctype controllers and the client module — so this can never become a
second implementation of the rules it displays.
"""

from __future__ import annotations

import frappe
from frappe import _

MAX_PAGE_LENGTH = 200


def _require_admin() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Managers may administer A2A."), frappe.PermissionError)


@frappe.whitelist()
def get_permissions() -> dict:
	"""What this user may do here — the UI asks before it renders controls."""
	is_admin = "System Manager" in frappe.get_roles()
	return {"administer": is_admin, "read": is_admin}


@frappe.whitelist()
def list_remote_agents() -> list[dict]:
	_require_admin()
	return frappe.get_all(
		"A2A Remote Agent",
		fields=[
			"name",
			"agent_name",
			"endpoint_url",
			"enabled",
			"approval_status",
			"card_name",
			"card_description",
			"card_fetched_at",
			"approved_by",
			"approved_on",
			"auth_scheme",
			"allow_internal_hosts",
			"default_task_timeout_minutes",
			"poll_base_interval",
			"poll_max_interval",
		],
		order_by="modified desc",
	)


@frappe.whitelist()
def list_clients() -> list[dict]:
	_require_admin()
	clients = frappe.get_all(
		"A2A Client",
		fields=[
			"name",
			"client_name",
			"enabled",
			"approval_status",
			"user",
			"description",
			"approved_by",
			"approved_on",
		],
		order_by="modified desc",
	)
	for client in clients:
		client["allowed_agents"] = frappe.get_all(
			"A2A Client Allowed Agent",
			filters={"parent": client["name"], "parenttype": "A2A Client"},
			pluck="agent_configuration",
		)
	return clients


@frappe.whitelist()
def list_tasks(
	direction: str = None,
	state: str = None,
	start: int = 0,
	page_length: int = 50,
) -> dict:
	"""Inbound and outbound tasks with their states, counters and deadlines."""
	_require_admin()
	filters: dict = {}
	if direction in ("Inbound", "Outbound"):
		filters["direction"] = direction
	if state:
		filters["state"] = state

	page_length = min(int(page_length or 50), MAX_PAGE_LENGTH)
	rows = frappe.get_all(
		"A2A Task",
		filters=filters,
		fields=[
			"name",
			"task_id",
			"direction",
			"state",
			"client",
			"remote_agent",
			"agent_configuration",
			"instance",
			"delegation_depth",
			"handoff_count",
			"task_execution_id",
			"deadline",
			"next_poll_at",
			"poll_attempts",
			"pending_human_task",
			"status_message",
			"error_message",
			"creation",
			"completed_at",
		],
		order_by="creation desc",
		start=int(start or 0),
		limit=page_length,
	)
	return {
		"tasks": rows,
		"total": frappe.db.count("A2A Task", filters),
		"start": int(start or 0),
		"page_length": page_length,
	}


@frappe.whitelist()
def exposed_agents() -> list[dict]:
	"""Agents that can appear on a client's allowed list: enabled, Live and
	exposed — the same rule the door and the card builder enforce."""
	_require_admin()
	return frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1, "lifecycle_status": "Live", "a2a_exposed": 1},
		fields=["name", "agent_id", "agent_name", "agent_type"],
		order_by="agent_name asc",
	)


@frappe.whitelist()
def fetch_remote_card(name: str) -> dict:
	"""Fetch and cache a remote's card — what an approver reviews."""
	_require_admin()
	return frappe.get_doc("A2A Remote Agent", name).fetch_card()


@frappe.whitelist()
def set_remote_approval(name: str, approval_status: str) -> dict:
	"""Approve, revoke or re-draft a remote entry. The controller owns the
	rules (a card is required to approve, stamps, endpoint resets)."""
	_require_admin()
	if approval_status not in ("Draft", "Approved", "Revoked"):
		frappe.throw(_("Unknown approval status '{0}'.").format(approval_status))
	doc = frappe.get_doc("A2A Remote Agent", name)
	doc.approval_status = approval_status
	doc.save()
	return {"name": doc.name, "approval_status": doc.approval_status}


@frappe.whitelist()
def set_client_approval(name: str, approval_status: str) -> dict:
	"""Approve a caller (issuing its service user and key) or revoke it
	(disabling that user immediately, affecting no other caller)."""
	_require_admin()
	if approval_status not in ("Draft", "Approved", "Revoked"):
		frappe.throw(_("Unknown approval status '{0}'.").format(approval_status))
	doc = frappe.get_doc("A2A Client", name)
	doc.approval_status = approval_status
	doc.save()
	doc.reload()
	return {"name": doc.name, "approval_status": doc.approval_status, "user": doc.user}


@frappe.whitelist()
def get_client_credentials(name: str) -> dict:
	"""The caller's API key and secret, for handing over out of band."""
	_require_admin()
	return frappe.get_doc("A2A Client", name).get_credentials()
