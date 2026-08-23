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
	agent_configuration: str = None,
	start: int = 0,
	page_length: int = 50,
) -> dict:
	"""Every delegation with its state, counters and deadline.

	Internal — one local agent handing work to another — is the primary case
	and belongs here with the rest. Leaving it out of the accepted directions
	silently dropped the filter and listed everything, which read as a broken
	filter rather than an unsupported one.
	"""
	_require_admin()
	filters: dict = {}
	if direction in ("Inbound", "Outbound", "Internal"):
		filters["direction"] = direction
	if state:
		filters["state"] = state
	# Which agent is doing the work. On a busy site the monitor is mostly one
	# agent's traffic at a time — "what has the Connector Agent been asked to
	# do" — and scrolling the whole list to answer that is not a filter.
	if agent_configuration:
		filters["agent_configuration"] = agent_configuration

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
			# Both ends of the hop: who asked, and who is doing it. Without
			# delegated_by an Internal row has no visible initiator at all.
			"delegated_by",
			"agent_configuration",
			"instance",
			# The whole story of one handoff, for the expandable row: what was
			# asked, what came back, and the two instances involved.
			"caller_instance",
			"request_payload",
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
		# Last updated, not created. A task's row changes as it moves — working,
		# input-required, timed-out — and a monitor is asked "what is happening
		# now", which is a different question from "what started most recently".
		order_by="modified desc",
		start=int(start or 0),
		limit=page_length,
	)
	return {
		"tasks": rows,
		"total": frappe.db.count("A2A Task", filters),
		"start": int(start or 0),
		"page_length": page_length,
	}


# ── Agent Delegation: the same hand-off, seen from the work it was for ──────
#
# The task monitor answers "what is in flight between agents". A delegation
# answers "who is working on this Work Item, how far along, and did anything
# stop it" — the same hop with the business document attached and the limit
# that ended it recorded. Both belong on this screen; neither replaces the
# other, which is why this is a list of its own rather than more columns on
# the task table.

DELEGATION_FIELDS = [
	"name",
	"delegating_agent",
	"worker_agent",
	"status",
	"stopped_reason",
	"a2a_task",
	"reference_doctype",
	"reference_name",
	"orchestrator_instance",
	"worker_instance",
	"delegation_depth",
	"handoff_count",
	"attempt_count",
	"limit_value",
	"reached_value",
	"started_at",
	"ended_at",
	"notified_user",
	"notified_at",
	"instruction",
	"error_message",
	"creation",
	"modified",
]


@frappe.whitelist()
def list_delegations(
	a2a_task: str = None,
	reference_doctype: str = None,
	reference_name: str = None,
	status: str = None,
	start: int = 0,
	page_length: int = 50,
) -> dict:
	"""Delegations, newest activity first.

	Filtered the way the question is actually asked: by the task it belongs to,
	by what the work was about (doctype and document), and by where it got to.
	The two name filters match on a fragment — nobody types AD-01234 from
	memory, and "WI-0028" is how you find the run you were just looking at.
	"""
	_require_admin()
	filters: dict = {}
	if a2a_task:
		filters["a2a_task"] = ["like", f"%{a2a_task}%"]
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	if reference_name:
		filters["reference_name"] = ["like", f"%{reference_name}%"]
	if status:
		filters["status"] = status

	page_length = min(int(page_length or 50), MAX_PAGE_LENGTH)
	rows = frappe.get_all(
		"Agent Delegation",
		filters=filters,
		fields=DELEGATION_FIELDS,
		# Last updated: a delegation's row moves through Delegated, In Progress
		# and then Needs Review or Completed, so ordering by creation buries the
		# one that just changed under a dozen that started after it.
		order_by="modified desc",
		start=int(start or 0),
		limit=page_length,
	)
	return {
		"delegations": rows,
		"total": frappe.db.count("Agent Delegation", filters),
		"start": int(start or 0),
		"page_length": page_length,
	}


@frappe.whitelist()
def delegation_detail(name: str) -> dict:
	"""One delegation, with the two things the list cannot show.

	``task`` — the A2A row's own state and answer, because "Completed" on the
	delegation and what the worker actually said are different facts, and the
	turn-cap case is exactly where they diverge.

	``reference_title`` — what the document is called, so the modal names the
	work rather than only its id.
	"""
	_require_admin()
	row = frappe.db.get_value("Agent Delegation", name, DELEGATION_FIELDS, as_dict=True)
	if not row:
		frappe.throw(_("Delegation {0} not found.").format(name), frappe.DoesNotExistError)

	task = None
	if row.get("a2a_task"):
		task = frappe.db.get_value(
			"A2A Task",
			row["a2a_task"],
			["name", "state", "direction", "status_message", "error_message", "deadline", "completed_at"],
			as_dict=True,
		)

	reference_title = None
	if row.get("reference_doctype") and row.get("reference_name"):
		try:
			meta = frappe.get_meta(row["reference_doctype"])
			field = meta.get_title_field()
			if field and field != "name":
				reference_title = frappe.db.get_value(
					row["reference_doctype"], row["reference_name"], field
				)
		except Exception:
			# A reference to a doctype that no longer exists must not take the
			# modal down with it — the delegation is still worth reading.
			reference_title = None

	return {"delegation": row, "task": task, "reference_title": reference_title}


@frappe.whitelist()
def delegation_filter_options() -> dict:
	"""What is actually worth filtering by on this site.

	Built from the rows themselves rather than from the doctype's Select
	options: a status nothing has ever reached, or a doctype nothing has ever
	been delegated about, is a dead entry in a dropdown.
	"""
	_require_admin()

	def distinct(fieldname: str) -> list[str]:
		rows = frappe.get_all(
			"Agent Delegation",
			filters={fieldname: ["is", "set"]},
			fields=[fieldname],
			group_by=fieldname,
			order_by=f"{fieldname} asc",
			limit=MAX_PAGE_LENGTH,
		)
		return [r[fieldname] for r in rows if r.get(fieldname)]

	return {
		"statuses": distinct("status"),
		"doctypes": distinct("reference_doctype"),
		"workers": distinct("worker_agent"),
		# The task monitor's agent filter comes from the same idea: only agents
		# that have actually been handed work appear.
		"task_agents": [
			r["agent_configuration"]
			for r in frappe.get_all(
				"A2A Task",
				filters={"agent_configuration": ["is", "set"]},
				fields=["agent_configuration"],
				group_by="agent_configuration",
				order_by="agent_configuration asc",
				limit=MAX_PAGE_LENGTH,
			)
			if r.get("agent_configuration")
		],
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
