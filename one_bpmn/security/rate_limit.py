# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Per-user, per-agent throttling and automatic conversation freeze (WI-001968).

Two controls, both enforced at the invocation entry point so every agent surface
gets them at once rather than each one remembering to ask.

THE THROTTLE — a real sliding window
------------------------------------
A Redis sorted set per (user, agent), holding one member per message scored by
timestamp. Counting is "drop everything older than the window, then count what's
left", which slides continuously. The naive alternative — a counter that resets
on a clock boundary — lets someone send a full allowance at 11:59:59 and another
full allowance at 12:00:00, i.e. double the limit in two seconds, which is
exactly the burst a probe looks like.

THE FREEZE — containment, not throttling
----------------------------------------
Throttling slows a prober down; it does not stop them. So blocked attempts are
counted too, and once a user accumulates enough against one agent the
conversation is frozen and a reviewer has to let them back in. The count comes
from the AI Security Event log rather than a private counter, so what triggered
a freeze is auditable after the fact and survives a Redis flush.

FAILS OPEN, LIKE THE SCREENS AROUND IT
--------------------------------------
If Redis is unreachable or the settings are unreadable, the turn proceeds. This
protects against abuse; it is not an authorisation check, and taking every
conversation on the site offline because a cache blipped is a far worse outcome
than a prober getting a few extra messages through. The one thing that does NOT
fail open is an existing lock — see ``enforce``.
"""

from __future__ import annotations

import time

import frappe
from frappe import _

# Settings and their defaults, read together so one query serves a whole turn.
_DEFAULTS = {
	"rate_limit_enabled": 1,
	"rate_limit_messages": 20,
	"rate_limit_window_seconds": 60,
	"lock_after_blocks": 3,
	"lock_block_window_seconds": 3600,
	"lock_release_roles": "AI Security Reviewer",
}


class RateLimited(frappe.ValidationError):
	"""Raised when a turn is refused. Carries why, so the caller can say so."""


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


def _window_key(user: str, agent: str) -> bytes:
	"""Site-namespaced Redis key. make_key keeps sites on a shared Redis apart."""
	return frappe.cache().make_key(f"ai_rate_limit:{user}:{agent}")


def record_and_count(user: str, agent: str, window_seconds: int, member: str | None = None) -> int:
	"""Add this attempt to the window and return how many are in it now.

	``member`` makes the entry idempotent: one turn can reach enforcement twice
	(once at the API entry point, once when its Chat Message is written), and
	passing the turn's correlation id both times means the sorted set overwrites
	rather than double-counts. Without it a single message would burn two of the
	user's allowance.

	Returns -1 when the count could not be taken, which callers read as "do not
	throttle" rather than "zero" — a cache failure must not silently look like a
	quiet user.
	"""
	try:
		cache = frappe.cache()
		key = _window_key(user, agent)
		now = time.time()
		cutoff = now - max(int(window_seconds or 0), 1)

		if not member:
			from one_bpmn.security.turn import current_correlation_id

			member = current_correlation_id()
		# Without a turn id, fall back to a unique member — two messages in the
		# same millisecond must not collapse into one.
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


def blocked_attempts(user: str, agent: str | None, window_seconds: int) -> int:
	"""Blocked attempts by this user against this agent inside the window.

	Read from AI Security Event rather than a counter, so the evidence behind a
	freeze is auditable and survives a cache flush.

	What counts as "blocked": an event whose action is Block — a refusal that
	actually happened — or a High/Critical injection match. The second is
	included deliberately: injection screening is record-only until 15.1, so
	without it a determined prober would never accumulate a single strike, and
	the freeze in this story would be unreachable in practice.
	"""
	from frappe.utils import add_to_date, now_datetime

	try:
		since = add_to_date(now_datetime(), seconds=-max(int(window_seconds or 0), 1))
		filters = {"owner": user, "creation": (">=", since)}
		if agent:
			filters["agent_configuration"] = agent

		blocks = frappe.db.count("AI Security Event", {**filters, "action": "Block"})
		serious = frappe.db.count(
			"AI Security Event",
			{**filters, "stage": "injection", "severity": ("in", ["High", "Critical"])},
		)
		return blocks + serious
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
	"""Freeze the conversation. Returns the lock name, or None if it failed.

	Idempotent: a user who is already frozen does not collect a second lock, or
	releasing one would leave them still locked by another.
	"""
	from one_bpmn.one_bpmn.doctype.ai_conversation_lock.ai_conversation_lock import active_lock

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
		return doc.name
	except Exception:
		frappe.log_error(
			title="AI rate limit: could not raise conversation lock",
			message=frappe.get_traceback(),
		)
		return None


def enforce(user: str, agent: str | None, agent_label: str, conversation: str | None) -> None:
	"""Gate one turn. Raises RateLimited when the turn must not proceed.

	Order matters. An existing lock is checked FIRST and is the one thing here
	that does not fail open — a frozen conversation stays frozen even if every
	other part of this module is having a bad day.
	"""
	from one_bpmn.one_bpmn.doctype.ai_conversation_lock.ai_conversation_lock import active_lock
	from one_bpmn.security.events import record_event

	# 1. Already frozen? Nothing else matters.
	lock = active_lock(user, agent, conversation)
	if lock:
		record_event(
			boundary="input", stage="conversation-lock", action="Block",
			agent_configuration=agent, conversation=conversation,
			severity="High", classifier="locked",
			detail=f"refused: conversation frozen by lock {lock}",
		)
		frappe.throw(
			_(
				"This conversation has been frozen after repeated blocked attempts. "
				"A reviewer needs to release it before you can continue."
			),
			RateLimited,
			title=_("Conversation Frozen"),
		)

	cfg = settings()
	if not int(cfg.get("rate_limit_enabled") or 0):
		return

	# 2. Throttle.
	limit = int(cfg.get("rate_limit_messages") or 0)
	window = int(cfg.get("rate_limit_window_seconds") or 60)
	if limit > 0:
		count = record_and_count(user, agent_label, window)
		if count > limit:
			event = record_event(
				boundary="input", stage="rate-limit", action="Block",
				agent_configuration=agent, conversation=conversation,
				severity="Medium", classifier="rate-limit",
				detail=f"refused: {count} messages in {window}s, limit {limit}",
			)
			_maybe_freeze(user, agent, conversation, cfg, trigger_event=event)
			frappe.throw(
				_("You are sending messages to this agent too quickly. Wait a moment and try again."),
				RateLimited,
				title=_("Rate Limit Reached"),
			)

	# 3. Enough blocked attempts to warrant containment? A freeze raised now
	#    refuses THIS message too — having decided the user is probing, letting
	#    the message that tipped the scale through is a strange place to stop.
	if _maybe_freeze(user, agent, conversation, cfg):
		frappe.throw(
			_(
				"This conversation has been frozen after repeated blocked attempts. "
				"A reviewer needs to release it before you can continue."
			),
			RateLimited,
			title=_("Conversation Frozen"),
		)


def _maybe_freeze(user, agent, conversation, cfg, trigger_event=None) -> str | None:
	"""Freeze when blocked attempts have reached the threshold. Never raises.

	Returns the lock name when one was raised, so the caller can refuse the turn;
	None when the threshold was not met.
	"""
	threshold = int(cfg.get("lock_after_blocks") or 0)
	if threshold <= 0:
		return None

	window = int(cfg.get("lock_block_window_seconds") or 3600)
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
		from one_bpmn.security.events import record_event

		record_event(
			boundary="input", stage="conversation-lock", action="Block",
			agent_configuration=agent, conversation=conversation,
			severity="Critical", classifier="lockout",
			detail=f"conversation frozen after {count} blocked attempts; lock {lock}",
		)
	return lock
