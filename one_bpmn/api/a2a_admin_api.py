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
from frappe.utils import get_url

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
def list_agent_cards() -> list[dict]:
	"""Our own exposed agents, each with the card the world would fetch.

	Admin only, deliberately. Individual cards are public because the spec
	expects an unauthenticated fetch, but a public INDEX of every agent
	would hand an outsider an enumeration list for free — so the catalogue
	is not the same thing as the cards it lists.

	Cards are built here rather than read from anywhere, for the same reason
	the endpoint builds them: there is no stored copy to drift.
	"""
	_require_admin()
	from one_bpmn.agents.a2a.card import RPC_PATH, build_agent_card

	rows = []
	for agent in frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1, "lifecycle_status": "Live", "a2a_exposed": 1},
		fields=["name", "agent_id", "agent_name", "agent_type", "a2a_skill_tags", "modified"],
		order_by="agent_name asc",
	):
		card = build_agent_card(agent.agent_id)
		if not card:
			continue
		skill = (card.get("skills") or [{}])[0]
		rows.append(
			{
				"name": agent.name,
				"agent_id": agent.agent_id,
				"agent_name": agent.agent_name,
				"agent_type": agent.agent_type,
				"description": card.get("description"),
				"tags": skill.get("tags") or [],
				"examples": skill.get("examples") or [],
				"card_url": get_url(f"/api/method/one_bpmn.api.a2a_api.agent_card?agent_id={agent.agent_id}"),
				"rpc_url": card.get("url"),
				"sub_agents": card.get("subAgents") or [],
				"reachable_by": _clients_that_may_reach(agent.name),
				"card": card,
			}
		)
	return rows


def _clients_that_may_reach(agent_configuration: str) -> list[str]:
	"""Which approved callers list this agent. Empty means: exposed, with a
	public card, but no outside caller can actually reach it yet."""
	parents = frappe.get_all(
		"A2A Client Allowed Agent",
		filters={"agent_configuration": agent_configuration, "parenttype": "A2A Client"},
		pluck="parent",
	)
	if not parents:
		return []
	return frappe.get_all(
		"A2A Client",
		filters={"name": ("in", parents), "enabled": 1, "approval_status": "Approved"},
		pluck="name",
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


# ── Registering and editing, so the whole lifecycle lives on this screen ──────
#
# WI-001934 asks for "register an endpoint" here. Everything below exists so
# nobody has to open Desk to add a partner or a caller: the fields a person
# fills in are the fields these accept, and the doctype controllers still own
# every rule (approval needs a card, an endpoint change resets approval, an
# approved client gets its key).

REMOTE_EDITABLE = (
	"endpoint_url",
	"enabled",
	"auth_scheme",
	"auth_header_name",
	"credential",
	"allow_internal_hosts",
	"request_timeout",
	"default_task_timeout_minutes",
	"poll_base_interval",
	"poll_max_interval",
)


def _clean_endpoint(url: str) -> str:
	"""A typo caught here is cheaper than a card fetch that fails later."""
	url = (url or "").strip()
	if not url:
		frappe.throw(_("An endpoint URL is required."), title=_("Remote Agent"))
	if not url.lower().startswith(("http://", "https://")):
		frappe.throw(
			_("The endpoint URL must start with http:// or https://."), title=_("Remote Agent")
		)
	return url


@frappe.whitelist()
def create_remote_agent(agent_name: str, endpoint_url: str, **fields) -> dict:
	"""Register a remote agent. It starts in Draft: fetching its card and
	approving it are separate, deliberate steps."""
	_require_admin()
	agent_name = (agent_name or "").strip()
	if not agent_name:
		frappe.throw(_("A name is required."), title=_("Remote Agent"))
	if frappe.db.exists("A2A Remote Agent", agent_name):
		frappe.throw(_("A remote agent called '{0}' already exists.").format(agent_name))

	doc = frappe.new_doc("A2A Remote Agent")
	doc.agent_name = agent_name
	doc.endpoint_url = _clean_endpoint(endpoint_url)
	doc.approval_status = "Draft"
	for field in REMOTE_EDITABLE:
		if field in fields and fields[field] not in (None, ""):
			doc.set(field, fields[field])
	doc.insert()
	return {"name": doc.name, "approval_status": doc.approval_status}


@frappe.whitelist()
def update_remote_agent(name: str, **fields) -> dict:
	"""Edit a registered remote. Changing the endpoint sends it back to Draft —
	the controller does that, not this endpoint."""
	_require_admin()
	doc = frappe.get_doc("A2A Remote Agent", name)
	if "endpoint_url" in fields:
		fields["endpoint_url"] = _clean_endpoint(fields["endpoint_url"])
	for field in REMOTE_EDITABLE:
		if field in fields:
			doc.set(field, fields[field])
	doc.save()
	return {"name": doc.name, "approval_status": doc.approval_status}


@frappe.whitelist()
def create_client(client_name: str, description: str = None, allowed_agents=None) -> dict:
	"""Register a caller. Draft until approved, because approval is what issues
	its credentials."""
	_require_admin()
	client_name = (client_name or "").strip()
	if not client_name:
		frappe.throw(_("A name is required."), title=_("A2A Client"))
	if frappe.db.exists("A2A Client", client_name):
		frappe.throw(_("A client called '{0}' already exists.").format(client_name))

	doc = frappe.new_doc("A2A Client")
	doc.client_name = client_name
	doc.description = description
	doc.approval_status = "Draft"
	for agent in _agent_list(allowed_agents):
		doc.append("allowed_agents", {"agent_configuration": agent})
	doc.insert()
	return {"name": doc.name, "approval_status": doc.approval_status}


@frappe.whitelist()
def set_client_agents(name: str, allowed_agents=None) -> dict:
	"""Replace which agents a caller may reach. Takes effect immediately — the
	door reads this list on every call."""
	_require_admin()
	doc = frappe.get_doc("A2A Client", name)
	doc.allowed_agents = []
	for agent in _agent_list(allowed_agents):
		doc.append("allowed_agents", {"agent_configuration": agent})
	doc.save()
	return {
		"name": doc.name,
		"allowed_agents": [row.agent_configuration for row in doc.allowed_agents],
	}


def _agent_list(value) -> list[str]:
	"""Accept a JSON string (what the browser sends) or a list, and keep only
	agents that are actually exposed — a client cannot be granted an agent that
	does not take part in A2A."""
	if isinstance(value, str):
		value = frappe.parse_json(value or "[]")
	names = [str(v) for v in (value or []) if v]
	if not names:
		return []
	return frappe.get_all(
		"AI Agent Configuration",
		filters={
			"name": ("in", names),
			"enabled": 1,
			"lifecycle_status": "Live",
			"a2a_exposed": 1,
		},
		pluck="name",
	)
