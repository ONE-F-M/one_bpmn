# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Session administration for Processa: what a conversation is doing, and what
happens to it when it goes quiet.

Everything a process owner needs to answer "why does this agent not remember
that?" or "where did that conversation go?" without opening Desk. Three things
were only visible there: whether a conversation is still live, what its stored
summary actually says, and how long conversations are kept before being
archived or deleted.

Read endpoints are deliberately cheap enough to poll: the listing aggregates
counts in SQL rather than loading documents, because a site with a few thousand
conversations should not pay for a full read to draw a table.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from one_bpmn.agents.memory.compaction import (
	CONVERSATION_DOCTYPE,
	MESSAGE_DOCTYPE,
	SUMMARY_DOCTYPE,
	VISIBLE_MESSAGE_TYPES,
)
from one_bpmn.agents.memory.conversation_store import AGENT_MEMORY_MODE
from one_bpmn.agents.memory.retention import ARCHIVED_STATUS, last_activity, retention_config
from one_bpmn.agents.memory.session_state import STATE_DOCTYPE

# A conversation with no message newer than this reads as Idle. Presentation
# only — retention decides what actually happens, and does so from its own TTL.
IDLE_AFTER_HOURS = 24


def _guard():
	"""Session administration is a System Manager job.

	It exposes conversation titles and summary text across every user's chats,
	so it is gated harder than the rest of the editor — a Process Designer can
	build maps without being able to read what other people said to an agent.
	"""
	if frappe.session.user == "Administrator":
		return
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Session administration requires the System Manager role."), frappe.PermissionError)


def _display_status(status: str, last: object) -> str:
	"""Active / Idle / Archived, as the AC names them.

	Archived is a real stored state. Active and Idle are not — they are one
	stored value ("Open") split by whether anybody has spoken recently, because
	"open but untouched for a fortnight" and "open and in use" are the same row
	and a very different thing to the person reading the screen.
	"""
	if status == ARCHIVED_STATUS:
		return "Archived"
	if not last:
		return "Idle"
	return "Active" if last > add_to_date(now_datetime(), hours=-IDLE_AFTER_HOURS) else "Idle"


@frappe.whitelist()
def list_conversations(agent: str = None, status: str = None, search: str = None,
                       limit: int = 50) -> dict:
	"""Conversations with their lifecycle at a glance.

	Counts come from grouped SQL rather than per-row lookups: drawing a
	fifty-row table should be a handful of queries, not two hundred.
	"""
	_guard()
	limit = min(max(cint(limit) or 50, 1), 200)

	filters = {"agent_mode": ["!=", AGENT_MEMORY_MODE]}
	if agent:
		filters["agent_mode"] = agent
	if search:
		filters["title"] = ["like", f"%{search}%"]
	if status == "Archived":
		filters["status"] = ARCHIVED_STATUS
	elif status in ("Active", "Idle"):
		filters["status"] = ["!=", ARCHIVED_STATUS]

	rows = frappe.get_all(
		CONVERSATION_DOCTYPE,
		filters=filters,
		fields=["name", "title", "agent_mode", "status", "modified"],
		order_by="modified desc",
		limit_page_length=limit,
	)
	names = [r["name"] for r in rows]
	if not names:
		return {"conversations": [], "agents": _agent_modes(), "retention": get_retention()}

	messages = _count_by(MESSAGE_DOCTYPE, "conversation", names,
	                     extra="AND message_type IN %(types)s",
	                     params={"types": tuple(VISIBLE_MESSAGE_TYPES)})
	summaries = _count_by(SUMMARY_DOCTYPE, "conversation", names)
	latest = _latest_message(names)
	stateful = set(frappe.get_all(STATE_DOCTYPE, filters={"name": ["in", names]}, pluck="name"))

	out = []
	for r in rows:
		last = latest.get(r["name"])
		display = _display_status(r["status"], last)
		if status in ("Active", "Idle") and display != status:
			continue
		out.append({
			"name": r["name"],
			"title": r["title"] or "(untitled)",
			"agent": r["agent_mode"],
			"status": display,
			"stored_status": r["status"],
			"messages": messages.get(r["name"], 0),
			"summaries": summaries.get(r["name"], 0),
			"has_state": r["name"] in stateful,
			"last_activity": str(last) if last else None,
		})
	return {"conversations": out, "agents": _agent_modes(), "retention": get_retention()}


def _count_by(doctype: str, field: str, names: list, extra: str = "", params: dict = None) -> dict:
	rows = frappe.db.sql(
		f"""SELECT `{field}` AS k, COUNT(*) AS n FROM `tab{doctype}`
		    WHERE `{field}` IN %(names)s {extra} GROUP BY `{field}`""",
		{"names": tuple(names), **(params or {})},
		as_dict=True,
	)
	return {r["k"]: r["n"] for r in rows}


def _latest_message(names: list) -> dict:
	rows = frappe.db.sql(
		"""SELECT conversation AS k, MAX(creation) AS c FROM `tabChat Message`
		   WHERE conversation IN %(names)s GROUP BY conversation""",
		{"names": tuple(names)}, as_dict=True,
	)
	return {r["k"]: r["c"] for r in rows}


def _agent_modes() -> list:
	rows = frappe.get_all(
		CONVERSATION_DOCTYPE,
		filters={"agent_mode": ["!=", AGENT_MEMORY_MODE]},
		fields=["distinct agent_mode as agent_mode"],
		limit_page_length=0,
	)
	return sorted([r["agent_mode"] for r in rows if r.get("agent_mode")])


@frappe.whitelist()
def conversation_detail(conversation: str) -> dict:
	"""Everything stored about one conversation, for debugging.

	The summaries are the point. "Why does the agent think the module is X" is
	usually answered by reading what its summary says, and until now that meant
	Desk.
	"""
	_guard()
	if not conversation or not frappe.db.exists(CONVERSATION_DOCTYPE, conversation):
		frappe.throw(_("No such conversation: {0}").format(conversation))

	conv = frappe.db.get_value(
		CONVERSATION_DOCTYPE, conversation,
		["name", "title", "agent_mode", "status", "creation", "modified"], as_dict=True,
	)
	last = _latest_message([conversation]).get(conversation)

	summaries = frappe.get_all(
		SUMMARY_DOCTYPE,
		filters={"conversation": conversation},
		fields=["name", "summary", "covered_count", "covered_upto", "model", "agent_id",
		        "supersedes", "creation"],
		order_by="covered_upto desc",
	)

	state = {}
	state_version = 0
	if frappe.db.exists(STATE_DOCTYPE, conversation):
		doc = frappe.get_doc(STATE_DOCTYPE, conversation)
		state_version = cint(doc.version)
		for row in doc.entries or []:
			try:
				state[row.key] = json.loads(row.value) if row.value else None
			except (ValueError, TypeError):
				state[row.key] = row.value

	return {
		"conversation": {
			**conv,
			"status": _display_status(conv["status"], last),
			"stored_status": conv["status"],
			"last_activity": str(last) if last else None,
			"messages": _count_by(MESSAGE_DOCTYPE, "conversation", [conversation],
			                      extra="AND message_type IN %(types)s",
			                      params={"types": tuple(VISIBLE_MESSAGE_TYPES)}).get(conversation, 0),
		},
		"summaries": summaries,
		"state": state,
		"state_version": state_version,
	}


@frappe.whitelist()
def compact_now(conversation: str) -> dict:
	"""Queue compaction for one conversation, by hand.

	The triggers decide when normally; this is for the moment somebody is
	looking at a conversation and wants to see what a summary would say. It
	QUEUES rather than runs — the same rule as everywhere else, because
	summarising is a model call and a settings screen must not block on one.
	"""
	_guard()
	from one_bpmn.agents.memory.compaction import needs_compaction
	from one_bpmn.agents.memory.compaction_triggers import (
		_is_inflight,
		_resolve_agent_id,
		enqueue_compaction,
		trigger_config,
	)

	if not frappe.db.exists(CONVERSATION_DOCTYPE, conversation):
		frappe.throw(_("No such conversation: {0}").format(conversation))

	# Ask the same three questions the trigger asks, in the same order, so the
	# button can say WHICH one stopped it. A button that silently does nothing
	# is the complaint that started this whole epic, and "nothing happened, for
	# one of three reasons" is barely better.
	agent_id = _resolve_agent_id(conversation)
	cfg = trigger_config(agent_id)
	if not cfg:
		return {"queued": False, "reason": _(
			"Compaction is switched off for this agent. Turn it on in its agent "
			"configuration, under Memory."
		)}
	if not needs_compaction(conversation, cfg["keep_tail"]):
		return {"queued": False, "reason": _(
			"Nothing above the recent-messages tail yet — this conversation has no "
			"history older than the last {0} messages it always keeps verbatim."
		).format(cfg["keep_tail"])}
	if _is_inflight(conversation):
		return {"queued": False, "reason": _(
			"A compaction for this conversation is already queued."
		)}

	queued = enqueue_compaction(conversation, reason="manual", cfg=cfg, agent_id=agent_id)
	return {
		"queued": queued,
		"reason": None if queued else _("Could not queue compaction — try again in a moment."),
	}


@frappe.whitelist()
def get_retention() -> dict:
	"""The site's retention settings, plus what they would currently affect."""
	_guard()
	cfg = retention_config()
	ttl = cint(frappe.db.get_single_value("Processa Settings", "conversation_ttl_days"))
	action = frappe.db.get_single_value("Processa Settings", "archive_action") or "Archive"
	affected = 0
	if cfg:
		from one_bpmn.agents.memory.retention import expired_conversations
		affected = len(expired_conversations(cfg["ttl_days"]))
	return {
		"ttl_days": ttl,
		"archive_action": action,
		"enabled": bool(cfg),
		# What the next sweep would act on, so nobody turns Delete on without
		# seeing the size of it first.
		"would_affect": affected,
	}


@frappe.whitelist()
def save_retention(ttl_days: int, archive_action: str) -> dict:
	"""Write the site retention settings from the SPA."""
	_guard()
	ttl = cint(ttl_days)
	if ttl < 0:
		frappe.throw(_("A retention period cannot be negative. Use 0 to switch retention off."))
	if archive_action not in ("Archive", "Delete"):
		frappe.throw(_("Action on expiry must be Archive or Delete."))

	settings = frappe.get_single("Processa Settings")
	settings.conversation_ttl_days = ttl
	settings.archive_action = archive_action
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return get_retention()


@frappe.whitelist()
def agent_compaction_summary() -> list:
	"""Which agents compact, and how — so the screen can say what is switched on
	without making somebody open six agent configurations to find out."""
	_guard()
	rows = frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1},
		fields=["name", "agent_id", "chat_mode_label", "compaction_enabled",
		        "compaction_keep_tail", "compaction_model", "compaction_token_threshold",
		        "compaction_idle_minutes", "compaction_on_task_boundary",
		        "context_token_budget"],
		order_by="chat_mode_label asc",
	)
	return [r for r in rows if r.get("chat_mode_label")]
