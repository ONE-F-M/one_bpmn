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

from one_bpmn.security.refusal import AgentRefusal

# The one genuinely site-wide setting left: WHO may release a frozen
# conversation. That is a statement about roles on this site and means nothing
# per agent — everything else about how hard an agent pushes back is the
# agent's own (see _AGENT_DEFAULTS).
_DEFAULTS = {
	"lock_release_roles": "AI Security Reviewer",
}

# Per-agent limits: the throttle, and the freeze thresholds. Used only when the
# agent cannot be read at all — a normal agent carries its own values, which the
# doctype defaults to these same numbers.
_AGENT_DEFAULTS = {
	"rate_limit_enabled": 1,
	"rate_limit_messages": 20,
	"rate_limit_window_seconds": 60,
	"lock_after_blocks": 3,
	"lock_block_window_seconds": 3600,
}


class RateLimited(AgentRefusal):
	"""Raised when a turn is refused. Carries why, so the caller can say so.

	Derives from AgentRefusal (WI-001840) so the engine's "a refusal is not a
	fault" rule covers every control by category rather than by name. Still a
	ValidationError, so existing handlers are unaffected.
	"""


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
	"""The throttle and freeze thresholds for one agent.

	Both are the agent's own rather than one number for the whole site: a limit
	that suits a chat assistant throttles a batch agent to a standstill, and an
	agent that fields adversarial traffic all day should not freeze users at the
	same threshold as one that never sees any.

	Read together in a single query because a turn needs both and they are asked
	for in the same breath.

	``agent`` may be an AI Agent Configuration name or the resolved config dict.
	The dict is CURATED — it carries agent_id but not these fields — so it is
	resolved back to the record rather than read from directly, which is the
	mistake that made output screening silently fall back to its default.

	Falls back to the defaults on any read failure, matching the module's
	fail-open stance: an unreadable agent gets the ordinary limits, neither left
	unprotected nor taken offline.
	"""
	out = dict(_AGENT_DEFAULTS)
	try:
		from one_bpmn.security.pii import _config_name

		name = _config_name(agent)
		if not name:
			return out
		row = frappe.db.get_value(
			"AI Agent Configuration", name, list(_AGENT_DEFAULTS), as_dict=True
		)
		if not row:
			return out
		for key in _AGENT_DEFAULTS:
			value = row.get(key)
			# 0 is a real answer for every one of these — "off", "no allowance",
			# "never freeze" — so only a genuinely absent value falls through.
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


def peek_count(user: str, agent: str, window_seconds: int) -> int:
	"""How many attempts are in the window, without adding one.

	Used by the gate that checks but does not count, so a turn passing two gates
	is still one attempt. Returns -1 on failure, which callers read as "do not
	throttle" — the same fail-open posture as record_and_count.
	"""
	try:
		key = _window_key(user, agent)
		cutoff = time.time() - max(int(window_seconds or 0), 1)
		return int(frappe.cache().zcount(key, cutoff, "+inf"))
	except Exception:
		return -1


def clear_window(user: str, agent) -> int:
	"""Forget this user's throttle history for one agent. Returns keys cleared.

	Called when a reviewer releases a frozen conversation. Without it a release
	does almost nothing: the window that was full when the freeze happened is
	still full, so the released user's very next message is refused and they are
	told to wait — for up to the whole window — despite a human having just
	decided they may carry on.

	Clears under both labels the window can be keyed by. Enforcement keys on the
	agent_id (``prosally_agent``), while a lock records the configuration name
	(``prosally``), and callers reach this with either.
	"""
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
			# Letting delete_value prefix it a second time deletes a key that
			# does not exist and reports success, which is exactly what happened:
			# the release looked clean and the window was still full.
			frappe.cache().delete_value(_window_key(user, label), make_keys=False)
			cleared += 1
		except Exception:
			# A cache that cannot be cleared leaves the user waiting out the
			# window — worse than instant, but not a reason to fail the release.
			pass
	return cleared


def _strikes_reset_at(user: str, agent: str | None):
	"""When this user's blocked attempts against this agent were last forgiven.

	A release draws a line. Strikes from before it have been reviewed and
	answered by a human decision, so counting them again would re-freeze the
	conversation on the released user's next refusal — which is the same as not
	having released it.

	Nothing is deleted: the events stay in the log for audit, they simply stop
	counting toward the NEXT freeze.
	"""
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
		# A release forgives everything before it, so the count starts there
		# rather than at the top of the window.
		forgiven_until = _strikes_reset_at(user, agent)
		if forgiven_until and forgiven_until > since:
			since = forgiven_until
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
		# COMMIT before returning. The caller's next act is frappe.throw, which
		# rolls the whole request back — so without this the freeze was told to
		# the user and then undone: "a reviewer needs to release it" with no lock
		# for anyone to release, and the very next message going straight
		# through. Observed live (WI-001840 testing).
		#
		# Same rule the streamed refusal already follows: a refusal is a
		# DECISION, and the record of it has to outlive the exception that
		# carries it. in_test is excepted because FrappeTestCase rolls back
		# deliberately and a commit here would leak fixtures between tests.
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
	"""Gate one turn. Raises RateLimited when the turn must not proceed.

	Order matters. An existing lock is checked FIRST and is the one thing here
	that does not fail open — a frozen conversation stays frozen even if every
	other part of this module is having a bad day.

	``count`` decides whether this call ADDS the turn to the window or merely
	reads it. A chat turn passes two gates — the API entry point and the write
	of its Chat Message — and must be counted once. Correlation-id dedup cannot
	do that job: the map runs the turn in a worker thread and a ContextVar does
	not cross threads, so each gate minted its own id and one message consumed
	two of the user's allowance. Counting is therefore pinned to exactly one
	gate per turn, chosen by the caller.
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
		# Same reason as raise_lock: the throw below rolls this back otherwise,
		# and a refusal nobody can see afterwards is indistinguishable from one
		# that never happened.
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

	# 2. Throttle — the agent's own allowance.
	if not int(limits.get("rate_limit_enabled") or 0):
		# The freeze still applies. Exempting an agent from the throttle says
		# "this one is chatty", not "stop containing people who probe it".
		if _maybe_freeze(user, agent, conversation, limits):
			frappe.throw(
				_(
					"This conversation has been frozen after repeated blocked attempts. "
					"A reviewer needs to release it before you can continue."
				),
				RateLimited,
				title=_("Conversation Frozen"),
			)
		return

	limit = int(limits.get("rate_limit_messages") or 0)
	window = int(limits.get("rate_limit_window_seconds") or 60)
	if limit > 0:
		# READ FIRST, and record only what is actually allowed through.
		#
		# The window used to be written before it was checked, so a REFUSED
		# attempt landed in it too. Every retry then pushed a fresh entry with a
		# fresh timestamp, and the window could not drain while the user kept
		# trying — the refusal became permanent for anyone who did the obvious
		# thing and tried again. Someone on 3-in-180s retrying every 20 seconds
		# would never get back in.
		#
		# A rejected message is not a message the agent handled, so it does not
		# spend the allowance. It is still recorded as a security event below:
		# the attempt is auditable and still counts toward a freeze, which is the
		# control meant to deal with someone hammering the door.
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

		# Allowed. Now it counts — and only at the gate designated to count, so a
		# turn crossing two gates spends one of the allowance rather than two.
		if count:
			record_and_count(user, agent_label, window)

	# 3. Enough blocked attempts to warrant containment? A freeze raised now
	#    refuses THIS message too — having decided the user is probing, letting
	#    the message that tipped the scale through is a strange place to stop.
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
	"""Freeze when blocked attempts have reached the threshold. Never raises.

	Returns the lock name when one was raised, so the caller can refuse the turn;
	None when the threshold was not met.
	"""
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
		from one_bpmn.security.events import record_event

		record_event(
			boundary="input", stage="conversation-lock", action="Block",
			agent_configuration=agent, conversation=conversation,
			severity="Critical", classifier="lockout",
			detail=f"conversation frozen after {count} blocked attempts; lock {lock}",
		)
	return lock
