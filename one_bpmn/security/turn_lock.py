# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One turn at a time per conversation.

``receive_message`` restores the instance's ``workflow_state``, runs the engine
and writes the state back. Two deliveries that overlap each restore the SAME
state and the last write wins, so one turn's work is silently discarded — and
the transcript interleaves, with both questions landing before either answer.

The fix is a lock held for the length of a turn, keyed on the conversation. What
a second message does while it is held is the agent's own setting: wait its turn,
or be told the agent is still busy.

Redis, not a row lock: a chat turn runs for several seconds, and holding a
MariaDB transaction open that long blocks every other writer to the instance row.

The lock is taken with a raw ``SET NX EX`` rather than ``cache.set_value``.
``set_value`` with ``expires_in_sec`` writes only to Redis and skips Frappe's
in-process memo, so a read before the write poisons the memo and the guard leaks
inside a single request.
"""

from __future__ import annotations

import time
import uuid

import frappe
from frappe import _

from one_bpmn.security.refusal import AgentRefusal

# Longer than any turn we have seen, so a healthy turn never has its lock expire
# underneath it. A worker that dies mid-turn frees the conversation after this.
LOCK_TTL_SECONDS = 180
# How long a queued turn waits before giving up. Below the TTL, so a caller is
# never left waiting on a lock that has already gone stale.
QUEUE_WAIT_SECONDS = 150
_POLL_SECONDS = 0.2

QUEUE = "Queue"
REFUSE = "Refuse"

# Used only when the agent cannot be read at all. Queuing is the default because
# it answers both messages; refusing is the choice you make deliberately.
_DEFAULT_POLICY = QUEUE


class TurnBusy(AgentRefusal):
	"""This conversation is already running a turn, and the agent refuses to queue.

	A refusal, not a fault: derives from AgentRefusal so the engine leaves the
	instance alone and the chat surface shows the reason verbatim.
	"""


def policy_for(agent) -> str:
	"""What this agent does with a message that arrives mid-turn.

	``agent`` may be an AI Agent Configuration name or the resolved config dict,
	which is curated and does not carry this field — so it is resolved back to
	the record, the same way limits_for does.
	"""
	try:
		from one_bpmn.security.pii import _config_name

		name = _config_name(agent)
		if not name:
			return _DEFAULT_POLICY
		value = frappe.db.get_value("AI Agent Configuration", name, "concurrent_turn_policy")
		return value if value in (QUEUE, REFUSE) else _DEFAULT_POLICY
	except Exception:
		return _DEFAULT_POLICY


def _key(conversation: str) -> bytes:
	"""Site-namespaced Redis key. make_key keeps sites on a shared Redis apart."""
	return frappe.cache().make_key(f"ai_turn_lock:{conversation}")


def acquire(conversation: str, policy: str = QUEUE, wait_seconds: float = None) -> str | None:
	"""Take the conversation's turn lock. Returns the token needed to release it.

	Returns None when there is nothing to lock (no conversation yet), so the
	caller can pass that straight back to ``release``.

	Raises TurnBusy when the agent's policy is Refuse and a turn is already
	running. Never raises on a Redis failure — a lock we cannot take must not
	take the chat down with it.
	"""
	if not conversation:
		return None

	token = uuid.uuid4().hex
	deadline = time.monotonic() + (
		QUEUE_WAIT_SECONDS if wait_seconds is None else wait_seconds
	)

	while True:
		try:
			# Inside the guard: building the key touches the cache client too, so
			# a Redis that is gone fails here rather than on the write.
			if frappe.cache().set(_key(conversation), token, nx=True, ex=LOCK_TTL_SECONDS):
				return token
		except Exception:
			# Redis unreachable. Fail open: the race is rare and a chat that
			# refuses every message is worse than one that occasionally overlaps.
			frappe.log_error(
				title="AI turn lock unavailable — turn allowed through",
				message=frappe.get_traceback(),
			)
			return None

		if policy == REFUSE:
			raise TurnBusy(_("Still working on your last message — one moment."))
		if time.monotonic() >= deadline:
			raise TurnBusy(
				_("Still working on your previous message. Please try again in a moment.")
			)
		time.sleep(_POLL_SECONDS)


def release(conversation: str, token: str | None) -> None:
	"""Release the lock, but only if we still hold it.

	The compare matters: a turn that overran its TTL no longer owns the lock, and
	deleting it blind would free somebody else's turn.
	"""
	if not (conversation and token):
		return
	try:
		cache = frappe.cache()
		key = _key(conversation)
		current = cache.get(key)
		if current is None:
			return
		if isinstance(current, bytes):
			current = current.decode()
		if current == token:
			cache.delete(key)
	except Exception:
		frappe.log_error(
			title="AI turn lock release failed", message=frappe.get_traceback()
		)


def is_held(conversation: str) -> bool:
	"""Whether a turn is running on this conversation. For tests and diagnostics."""
	if not conversation:
		return False
	try:
		return frappe.cache().get(_key(conversation)) is not None
	except Exception:
		return False
