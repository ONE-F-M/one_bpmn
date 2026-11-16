# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Per-user, per-agent throttling and automatic conversation freeze.

The throttle is a sliding window in a Redis sorted set per (user, agent). The freeze
counts blocked attempts from the AI Security Event log. Both fail open when Redis or
the settings are unreadable, except an existing lock, which is always enforced.
"""

from __future__ import annotations

import time

import frappe
from frappe import _

from processa.ai_agent_guardrails.refusal import AgentRefusal

# The one site-wide setting: who may release a frozen conversation. Everything else is per agent.
_DEFAULTS = {
	"lock_release_roles": "AI Security Reviewer",
}

# Per-agent limits, used only when the agent cannot be read at all.
_AGENT_DEFAULTS = {
	"rate_limit_enabled": 1,
	"rate_limit_messages": 20,
	"rate_limit_window_seconds": 60,
	"lock_after_blocks": 3,
	"lock_block_window_seconds": 3600,
}


class RateLimited(AgentRefusal):
	"""Raised when a turn is refused; a refusal, not a fault, and still a ValidationError."""


def settings() -> dict:
	"""The rate-limit settings, falling back to defaults on any read failure."""
	out = dict(_DEFAULTS)
	try:
		doc = frappe.get_cached_doc("Processa Settings")
		for key in _DEFAULTS:
			value = doc.get(key)
			if value not in (None, ""):
				out[key] = value
	except Exception:
		pass
	return out


def limits_for(agent) -> dict:
	"""The throttle and freeze thresholds for one agent, or the defaults on any read failure.

	``agent`` may be a configuration name or the resolved config dict, which is curated and
	does not carry these fields, so it is resolved back to the record first.
	"""
	out = dict(_AGENT_DEFAULTS)
	try:
		from processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import agent_config_name

		name = agent_config_name(agent)
		if not name:
			return out
		row = frappe.db.get_value(
			"AI Agent Configuration", name, list(_AGENT_DEFAULTS), as_dict=True
		)
		if not row:
			return out
		for key in _AGENT_DEFAULTS:
			value = row.get(key)
			# 0 is a real answer for every one of these, so only an absent value falls through.
			if value not in (None, ""):
				out[key] = value
	except Exception:
		pass
	return out


def _window_key(user: str, agent: str) -> bytes:
	"""Site-namespaced Redis key. make_key keeps sites on a shared Redis apart."""
	return frappe.cache().make_key(f"ai_rate_limit:{user}:{agent}")


def record_and_count(user: str, agent: str, window_seconds: int, member: str | None = None) -> int:
	"""Add this attempt to the window and return the count; -1 means the count could not be taken.

	``member`` makes the entry idempotent, so one turn reaching enforcement twice counts once.
	"""
	try:
		cache = frappe.cache()
		key = _window_key(user, agent)
		now = time.time()
		cutoff = now - max(int(window_seconds or 0), 1)

		if not member:
			from processa.ai_agent_security.turn import current_correlation_id

			member = current_correlation_id()
		# Without a turn id, use a unique member so two messages in one millisecond stay apart.
		member = member or f"{now:.6f}:{frappe.generate_hash(length=6)}"

		pipe = cache.pipeline()
		pipe.zremrangebyscore(key, 0, cutoff)
		pipe.zadd(key, {member: now})
		pipe.zcard(key)
		pipe.expire(key, max(int(window_seconds or 0), 1) * 2)
		return int(pipe.execute()[2])
	except Exception:
		frappe.log_error(
			title="AI rate limit: window read failed — turn allowed through",
			message=frappe.get_traceback(),
		)
		return -1


def peek_count(user: str, agent: str, window_seconds: int) -> int:
	"""How many attempts are in the window, without adding one; -1 on failure (do not throttle)."""
	try:
		key = _window_key(user, agent)
		cutoff = time.time() - max(int(window_seconds or 0), 1)
		return int(frappe.cache().zcount(key, cutoff, "+inf"))
	except Exception:
		return -1


def clear_window(user: str, agent) -> int:
	"""Forget this user's throttle history for one agent under both of its labels; returns keys cleared."""
	labels = {str(agent)} if agent else set()
	try:
		agent_id = frappe.db.get_value("AI Agent Configuration", agent, "agent_id")
		if agent_id:
			labels.add(agent_id)
	except Exception:
		pass

	cleared = 0
	for label in labels:
		try:
			# make_keys=False because _window_key already applied make_key.
			frappe.cache().delete_value(_window_key(user, label), make_keys=False)
			cleared += 1
		except Exception:
			# A cache that cannot be cleared leaves the user waiting out the window, which is not fatal.
			pass
	return cleared


def _strikes_reset_at(user: str, agent: str | None):
	"""When this user's blocked attempts against this agent were last forgiven by a release."""
	if not agent:
		return None
	try:
		return frappe.db.get_value(
			"AI Conversation Lock",
			{"user": user, "agent_configuration": agent, "status": "Released"},
			"released_at",
			order_by="released_at desc",
		)
	except Exception:
		return None


def blocked_attempts(user: str, agent: str | None, window_seconds: int) -> int:
	"""Blocked attempts by this user against this agent inside the window, counted once per turn."""
	from frappe.utils import add_to_date, now_datetime

	try:
		since = add_to_date(now_datetime(), seconds=-max(int(window_seconds or 0), 1))
		# A release forgives everything before it, so the count starts there.
		forgiven_until = _strikes_reset_at(user, agent)
		if forgiven_until and forgiven_until > since:
			since = forgiven_until
		filters = {"owner": user, "creation": (">=", since)}
		if agent:
			filters["agent_configuration"] = agent

		rows = frappe.get_all(
			"AI Security Event",
			or_filters=[
				{"action": "Block"},
				{"stage": "injection", "severity": ("in", ["High", "Critical"])},
			],
			filters=filters,
			fields=["name", "correlation_id"],
			limit_page_length=0,
		)
		# Collapse by turn; an event with no correlation id counts once on its own.
		turns = {r["correlation_id"] for r in rows if r["correlation_id"]}
		loose = sum(1 for r in rows if not r["correlation_id"])
		return len(turns) + loose
	except Exception:
		frappe.log_error(
			title="AI rate limit: blocked-attempt count failed — no freeze raised",
			message=frappe.get_traceback(),
		)
		return 0


def raise_lock(
	user: str,
	agent: str | None,
	conversation: str | None,
	*,
	reason: str,
	blocked_count: int,
	trigger_event: str | None = None,
	detail: str | None = None,
) -> str | None:
	"""Freeze the conversation; returns the lock name, or None if it failed. Idempotent."""
	from processa.ai_agent_security.doctype.ai_conversation_lock.ai_conversation_lock import active_lock

	try:
		existing = active_lock(user, agent, conversation)
		if existing:
			return existing

		doc = frappe.new_doc("AI Conversation Lock")
		doc.user = user
		doc.agent_configuration = agent if agent and frappe.db.exists("AI Agent Configuration", agent) else None
		doc.conversation = conversation
		doc.reason = reason
		doc.blocked_count = blocked_count
		doc.status = "Locked"
		doc.trigger_event = trigger_event
		doc.detail = detail
		doc.insert(ignore_permissions=True)
		# Commit now: the caller's frappe.throw rolls the request back and would undo the lock.
		if not frappe.flags.in_test:
			frappe.db.commit()
		return doc.name
	except Exception:
		frappe.log_error(
			title="AI rate limit: could not raise conversation lock",
			message=frappe.get_traceback(),
		)
		return None


def enforce(
	user: str,
	agent: str | None,
	agent_label: str,
	conversation: str | None,
	count: bool = True,
) -> None:
	"""Gate one turn and raise RateLimited when it must not proceed.

	An existing lock is checked first and never fails open. ``count`` decides whether this
	call adds the turn to the window, so a turn passing two gates is counted once.
	"""
	from processa.ai_agent_security.doctype.ai_conversation_lock.ai_conversation_lock import active_lock
	from processa.ai_agent_security.events import record_event

	# 1. Already frozen? Nothing else matters.
	lock = active_lock(user, agent, conversation)
	if lock:
		record_event(
			boundary="input", stage="conversation-lock", action="Block",
			agent_configuration=agent, conversation=conversation,
			severity="High", classifier="locked",
			detail=f"refused: conversation frozen by lock {lock}",
		)
		# Commit the refusal record, because the throw below rolls the request back.
		if not frappe.flags.in_test:
			frappe.db.commit()
		frappe.throw(
			_(
				"This conversation has been frozen after repeated blocked attempts. "
				"A reviewer needs to release it before you can continue."
			),
			RateLimited,
			title=_("Conversation Frozen"),
		)

	# Both the throttle and the freeze thresholds are the agent's, read once.
	limits = limits_for(agent or agent_label)

	# 2. Throttle - the agent's own allowance.
	if not int(limits.get("rate_limit_enabled") or 0):
		# Off means off: no throttle and no freeze. Messages Per Window of 0 keeps only the freeze.
		return

	limit = int(limits.get("rate_limit_messages") or 0)
	window = int(limits.get("rate_limit_window_seconds") or 60)
	if limit > 0:
		# Read first and record only what is let through, so refused retries cannot keep the window full.
		observed = peek_count(user, agent_label, window)
		# -1 means the count could not be taken; fail open rather than refuse.
		if observed >= limit and observed >= 0:
			event = record_event(
				boundary="input", stage="rate-limit", action="Block",
				agent_configuration=agent, conversation=conversation,
				severity="Medium", classifier="rate-limit",
				detail=f"refused: {observed} messages already in {window}s, limit {limit}",
			)
			_maybe_freeze(user, agent, conversation, limits, trigger_event=event)
			frappe.throw(
				_("You are sending messages to this agent too quickly. Wait a moment and try again."),
				RateLimited,
				title=_("Rate Limit Reached"),
			)

		# Allowed. Only the gate designated to count adds the turn to the window.
		if count:
			record_and_count(user, agent_label, window)

	# 3. Enough blocked attempts to warrant containment? A freeze refuses this message too.
	if _maybe_freeze(user, agent, conversation, limits):
		frappe.throw(
			_(
				"This conversation has been frozen after repeated blocked attempts. "
				"A reviewer needs to release it before you can continue."
			),
			RateLimited,
			title=_("Conversation Frozen"),
		)


def _maybe_freeze(user, agent, conversation, limits, trigger_event=None) -> str | None:
	"""Freeze when blocked attempts reach the threshold; returns the lock name or None. Never raises."""
	threshold = int(limits.get("lock_after_blocks") or 0)
	if threshold <= 0:
		return None

	window = int(limits.get("lock_block_window_seconds") or 3600)
	count = blocked_attempts(user, agent, window)
	if count < threshold:
		return None

	lock = raise_lock(
		user, agent, conversation,
		reason="Repeated Blocked Attempts",
		blocked_count=count,
		trigger_event=trigger_event,
		detail=f"{count} blocked attempts in {window}s (threshold {threshold})",
	)
	if lock:
		from processa.ai_agent_security.events import record_event

		record_event(
			boundary="input", stage="conversation-lock", action="Block",
			agent_configuration=agent, conversation=conversation,
			severity="Critical", classifier="lockout",
			detail=f"conversation frozen after {count} blocked attempts; lock {lock}",
		)
	return lock
