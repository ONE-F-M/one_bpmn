"""
When to compact a conversation.

Compaction itself lives in :mod:`one_bpmn.agents.memory.compaction` and knows
nothing about timing. This module decides WHEN it should happen, and its single
firm rule is that the answer is never "right now, on this thread".

Summarising is an LLM call. Running it inside a chat turn would put its latency
in front of the person waiting for a reply — the exact cost this is supposed to
remove. So every trigger ends at :func:`enqueue_compaction`, which hands the
work to a background worker and returns. Nothing here ever calls
``compact_conversation`` directly.

Three triggers, all independent and all optional, configured per agent:

- COUNT — the history this agent would send has grown past a token estimate.
  Checked when a message is written.
- TIME — nobody has touched the conversation for a while. Checked by a sweep.
- EVENT — a turn just ended. Checked when the agent's reply is written, so
  compaction is never considered part-way through a turn.

They are deliberately the same mechanism with different questions in front of
it: whichever fires, the work queued and the result stored are identical. That
is what makes "the time trigger behaves like the count trigger" true by
construction rather than by testing three code paths for parity.

The whole module is failure-tolerant by design. It runs off a hook on every
chat message, so a mistake here would break conversations rather than merely
fail to compact them — every entry point swallows its own errors.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime, time_diff_in_seconds

from one_bpmn.agents.memory.compaction import (
	CONVERSATION_DOCTYPE,
	MESSAGE_DOCTYPE,
	VISIBLE_MESSAGE_TYPES,
	_resolve_agent_id,
	build_history,
	needs_compaction,
)

# The dedicated AI-agent queue, which has its own worker in the Procfile. This
# matters for more than tidiness: the shared worker also serves ``default``, and
# a bulk operation there (a few hundred delete_dynamic_links jobs, say) will
# hold it for minutes. Compaction on its own queue is picked up by the idle
# dedicated worker instead of queueing behind unrelated bulk work.
COMPACTION_QUEUE = "bpmn_ai_agent"
COMPACTION_JOB_TIMEOUT = 600

# Compaction is short and its value decays: it exists so the NEXT turn sends
# less, so a summary that lands after the conversation is over has missed the
# point. It goes to the head of its queue ahead of longer-running agent work.
# Safe to do because this queue only ever carries agent jobs, and the in-flight
# marker means there is at most one compaction per conversation in it.
COMPACTION_AT_FRONT = True

# Fallback when Processa Settings has no estimate configured. Only used to
# compare against a threshold that is itself an estimate, so it does not need
# to be exact — it needs to be stable.
_DEFAULT_CHARS_PER_TOKEN = 4

# How long a conversation stays "already queued". Long enough that a burst of
# messages cannot queue the same work repeatedly, short enough that a worker
# lost mid-job does not block compaction for the rest of the day.
_INFLIGHT_SECONDS = 900

# A sweep must not be able to queue the whole table in one pass.
_SWEEP_LIMIT = 200

# Fallback send window when the agent leaves Context Window blank. Matches the
# limit the Build Context scripts carry today.
_DEFAULT_WINDOW = 20


def _inflight_key(conversation: str) -> str:
	return f"compaction_inflight:{conversation}"


def _is_inflight(conversation: str):
	"""The reason a compaction is already queued for this conversation, or None.

	Deliberately does NOT use Redis key expiry. ``set_value`` with
	``expires_in_sec`` writes only to Redis and skips frappe's in-process memo,
	while ``get_value`` prefers that memo — so the two disagree within a single
	request and the guard leaks intermittently (observed: every other call in a
	burst got through). Storing the time in the VALUE and judging staleness on
	read makes the check depend on one source instead of two.

	The memo is dropped before reading regardless, because another execution
	context may have written the marker since this one last looked — the same
	reason ``agents/turn_state.py`` reads past it.
	"""
	frappe.local.cache.pop(frappe.cache.make_key(_inflight_key(conversation)), None)
	marked = frappe.cache.get_value(_inflight_key(conversation))
	if not isinstance(marked, dict) or not marked.get("at"):
		return None
	if time_diff_in_seconds(now_datetime(), get_datetime(marked["at"])) > _INFLIGHT_SECONDS:
		# A worker that died mid-job must not lock the conversation out of
		# compaction for good, so a stale marker simply does not count.
		return None
	return marked.get("reason") or True


def _mark_inflight(conversation: str, reason: str) -> None:
	frappe.cache.set_value(
		_inflight_key(conversation),
		{"reason": reason, "at": str(now_datetime())},
	)


def _clear_inflight(conversation: str) -> None:
	frappe.cache.delete_value(_inflight_key(conversation))


# ── configuration ───────────────────────────────────────────────────────────
def trigger_config(agent_id: str | None) -> dict | None:
	"""The agent's compaction settings, or None when it has none / is disabled.

	Returning None rather than a dict of zeroes matters: every caller treats
	None as "this agent does not compact" and stops, so an agent that has never
	been configured does no work at all beyond this lookup.
	"""
	if not agent_id:
		return None
	try:
		row = frappe.db.get_value(
			"AI Agent Configuration",
			{"agent_id": agent_id},
			[
				"name",
				"context_max_messages",
				"compaction_enabled",
				"compaction_keep_tail",
				"compaction_model",
				"compaction_token_threshold",
				"compaction_idle_minutes",
				"compaction_on_task_boundary",
			],
			as_dict=True,
		)
	except Exception:
		return None
	if not row or not row.get("compaction_enabled"):
		return None
	return {
		"agent_config": row["name"],
		# How many messages this agent SENDS — distinct from keep_tail, which is
		# how many compaction leaves verbatim. The count trigger has to measure
		# the send window: measuring keep_tail would measure the floor rather
		# than the thing that grows, so the threshold could never be crossed.
		"window": int(row.get("context_max_messages") or 0) or _DEFAULT_WINDOW,
		"keep_tail": int(row.get("compaction_keep_tail") or 0) or 10,
		"model": row.get("compaction_model") or None,
		"token_threshold": int(row.get("compaction_token_threshold") or 0),
		"idle_minutes": int(row.get("compaction_idle_minutes") or 0),
		"on_task_boundary": bool(row.get("compaction_on_task_boundary")),
	}


def _chars_per_token() -> int:
	try:
		value = int(frappe.db.get_single_value("Processa Settings", "token_estimator_chars_per_token") or 0)
		return value if value > 0 else _DEFAULT_CHARS_PER_TOKEN
	except Exception:
		return _DEFAULT_CHARS_PER_TOKEN


def estimated_history_tokens(conversation: str, window: int = _DEFAULT_WINDOW) -> int:
	"""Size of the history this agent would actually send, in estimated tokens.

	``window`` is the agent's send window, NOT the compaction tail — measuring
	the tail would measure the floor compaction leaves behind, which cannot grow,
	so the threshold could never be crossed.

	Measured through ``build_history`` rather than by counting rows, so it also
	reflects what compaction has ALREADY achieved: once a summary exists the
	number drops, and a conversation does not keep re-triggering the threshold
	on history that is no longer being sent.
	"""
	history = build_history(conversation, limit=window)
	chars = sum(len(m.get("content") or "") for m in history)
	return chars // _chars_per_token()


# ── the one path everything funnels through ─────────────────────────────────
def enqueue_compaction(conversation: str, *, reason: str, cfg: dict | None = None,
                       agent_id: str | None = None) -> bool:
	"""Queue compaction for ``conversation``. Never runs it here.

	Returns True when this call queued the work, False when it did not — no
	agent, nothing to compact, or a job for this conversation is already in
	flight. The in-flight marker is what stops a burst of messages queueing the
	same summary a dozen times; it is a cache key rather than a database row
	because it is a short-lived fact about work, not a record of anything.
	"""
	if not conversation:
		return False
	agent_id = agent_id or _resolve_agent_id(conversation)
	cfg = cfg or trigger_config(agent_id)
	if not cfg:
		return False

	# Ask the cheap question before taking the marker: a conversation with
	# nothing above its tail must not be marked in flight, or a single early
	# trigger would suppress the real one fifteen minutes later.
	if not needs_compaction(conversation, cfg["keep_tail"]):
		return False

	if _is_inflight(conversation):
		return False
	_mark_inflight(conversation, reason)

	frappe.enqueue(
		"one_bpmn.agents.memory.compaction_triggers.run_compaction",
		queue=COMPACTION_QUEUE,
		timeout=COMPACTION_JOB_TIMEOUT,
		at_front=COMPACTION_AT_FRONT,
		conversation=conversation,
		agent_id=agent_id,
		keep_tail=cfg["keep_tail"],
		model=cfg["model"],
		reason=reason,
	)
	return True


def run_compaction(conversation: str, agent_id: str | None = None, keep_tail: int = 10,
                   model: str | None = None, reason: str = "") -> dict:
	"""The background job. The only place ``compact_conversation`` is called.

	Never raises: a worker that throws would retry the same doomed summary and
	fill the failed-job queue, and a conversation that cannot be compacted must
	simply carry on uncompacted.
	"""
	from one_bpmn.agents.memory.compaction import compact_conversation

	try:
		result = compact_conversation(
			conversation, keep_tail=keep_tail, model=model, agent_id=agent_id
		)
	except Exception:
		frappe.log_error(
			title="Conversation compaction job failed",
			message=f"conversation={conversation} reason={reason}\n{frappe.get_traceback()}",
		)
		result = {"compacted": False, "reason": "job raised"}
	finally:
		# Released whatever happened, so a failure does not lock the
		# conversation out of compaction until the marker expires.
		_clear_inflight(conversation)

	frappe.logger("one_bpmn").info(
		f"compaction[{reason}] {conversation}: {result.get('reason') or 'compacted'}"
	)
	return result


# ── COUNT and EVENT: the chat message hook ──────────────────────────────────
def on_chat_message(doc, method=None) -> None:
	"""Consider compaction after a message is written.

	Bound to ``after_insert`` rather than ``before_insert``: the message this
	turn just produced has to be part of the count, and a conversation whose
	insert then fails should not have queued work about it.

	This sits on EVERY chat message, so it must be cheap for the overwhelming
	majority of agents that do not compact — the config lookup returns None and
	it stops. And it must never raise: an exception here would break the chat
	itself, which is a far worse outcome than not compacting.
	"""
	try:
		if getattr(doc, "message_type", None) not in VISIBLE_MESSAGE_TYPES:
			return
		conversation = getattr(doc, "conversation", None)
		if not conversation:
			return

		agent_id = _resolve_agent_id(conversation)
		cfg = trigger_config(agent_id)
		if not cfg:
			return

		# EVENT — the agent has replied, so the turn is over. Checked first
		# because it is the cheaper question and the two are not exclusive.
		if cfg["on_task_boundary"] and doc.message_type == "Bot":
			enqueue_compaction(conversation, reason="turn-boundary", cfg=cfg, agent_id=agent_id)
			return

		# COUNT — the history being sent has outgrown its budget.
		threshold = cfg["token_threshold"]
		if threshold > 0 and estimated_history_tokens(conversation, cfg["window"]) > threshold:
			enqueue_compaction(conversation, reason="token-threshold", cfg=cfg, agent_id=agent_id)
	except Exception:
		frappe.log_error(
			title="Conversation compaction: trigger check failed",
			message=frappe.get_traceback(),
		)


# ── TIME: the idle sweep ────────────────────────────────────────────────────
def sweep_idle_conversations() -> dict:
	"""Queue compaction for conversations nobody has touched in a while.

	The time trigger cannot be a hook — its whole premise is that nothing is
	happening — so it is a sweep. It queues exactly the same job the other two
	do, which is what makes an idle conversation and a busy one end up with the
	same kind of summary.

	Bounded per pass so a site that switches this on for a busy agent does not
	queue thousands of jobs in one minute.
	"""
	queued = 0
	considered = 0
	try:
		agents = frappe.get_all(
			"AI Agent Configuration",
			filters={"compaction_enabled": 1, "compaction_idle_minutes": [">", 0]},
			fields=["agent_id", "chat_mode_label", "compaction_idle_minutes"],
		)
		for agent in agents:
			cfg = trigger_config(agent["agent_id"])
			if not cfg or cfg["idle_minutes"] <= 0:
				continue
			cutoff = add_to_date(now_datetime(), minutes=-cfg["idle_minutes"])

			# "Idle" is when the last MESSAGE landed, not when the conversation
			# row was last written — status changes and title edits touch the
			# parent without the conversation having moved on.
			conversations = frappe.get_all(
				CONVERSATION_DOCTYPE,
				filters={"agent_mode": agent.get("chat_mode_label") or agent["agent_id"]},
				pluck="name",
				limit_page_length=_SWEEP_LIMIT,
			)
			for conversation in conversations:
				last = frappe.db.get_value(
					MESSAGE_DOCTYPE,
					{"conversation": conversation, "message_type": ["in", list(VISIBLE_MESSAGE_TYPES)]},
					"creation",
					order_by="creation desc",
				)
				if not last or last > cutoff:
					continue
				considered += 1
				if enqueue_compaction(
					conversation, reason="idle", cfg=cfg, agent_id=agent["agent_id"]
				):
					queued += 1
	except Exception:
		frappe.log_error(
			title="Conversation compaction: idle sweep failed",
			message=frappe.get_traceback(),
		)
	return {"considered": considered, "queued": queued}
