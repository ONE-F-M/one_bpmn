"""
Conversation retention: a lifecycle for chat data, enforced daily.

Without this, chat conversations accumulate forever. That is not merely untidy —
it is the absence of a policy, and "we keep everything indefinitely" is a
decision nobody made and cannot answer for.

The sweep runs once a day and acts on conversations nobody has touched for
``conversation_ttl_days``, doing whatever ``archive_action`` says:

- **Archive** marks the conversation and leaves everything in place. Reversible,
  and the safer default.
- **Delete** removes the conversation and its messages permanently. That is the
  point of a retention policy — a Delete that quietly left the rows on disk
  would enforce no lifecycle at all and would be a false promise to whoever set
  it. Logged with counts before it happens.

Two boundaries matter more than the mechanics:

**Idle means nobody has spoken, not that the row is untouched.** Measured from
the newest Chat Message, falling back to the conversation's own creation for one
that never had any. ``last_updated`` looks like the obvious field and is unset
on nearly half the rows here, while ``modified`` is bumped by a status change or
a title edit — a conversation nobody has opened in months can look permanently
active by that measure.

**An agent's memory thread is never swept.** Those carry ``AGENT_MEMORY_MODE``
and are an AI Agent Task's own working state, not a conversation someone had.
Deleting one silently removes what a running agent remembers, and nobody would
connect that to a retention setting.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from one_bpmn.agents.memory.compaction import (
	CONVERSATION_DOCTYPE,
	MESSAGE_DOCTYPE,
	SUMMARY_DOCTYPE,
)
from one_bpmn.agents.memory.conversation_store import AGENT_MEMORY_MODE

ARCHIVED_STATUS = "Archived"

# One pass must not be able to act on the whole table. A retention policy that
# deletes ten thousand conversations in a single sweep is indistinguishable from
# an accident, and a bounded pass simply finishes the rest tomorrow.
SWEEP_LIMIT = 500


def retention_config() -> dict | None:
	"""``{ttl_days, action}``, or None when retention is off.

	None rather than zeroes so every caller has one thing to check: an
	unconfigured site does no work beyond this lookup, and cannot be surprised
	by a default that deletes something.
	"""
	try:
		ttl = cint(frappe.db.get_single_value("Processa Settings", "conversation_ttl_days"))
		if ttl <= 0:
			return None
		action = frappe.db.get_single_value("Processa Settings", "archive_action") or "Archive"
	except Exception:
		return None
	return {"ttl_days": ttl, "action": action}


def last_activity(conversation: str):
	"""When anything was last SAID in this conversation.

	Falls back to the conversation's own creation so a conversation that never
	carried a message still ages out rather than living forever.
	"""
	last = frappe.db.get_value(
		MESSAGE_DOCTYPE, {"conversation": conversation}, "creation", order_by="creation desc"
	)
	return last or frappe.db.get_value(CONVERSATION_DOCTYPE, conversation, "creation")


def expired_conversations(ttl_days: int, limit: int = SWEEP_LIMIT) -> list[str]:
	"""Conversations idle longer than ``ttl_days``, excluding agent memory.

	The cheap filter runs in SQL and the exact one in Python: ``modified`` is a
	sound OVER-estimate of activity (it is bumped by more things than messages,
	never fewer), so anything already fresh by that measure cannot be idle by the
	stricter one and need not be examined at all.
	"""
	cutoff = add_to_date(now_datetime(), days=-ttl_days)
	candidates = frappe.get_all(
		CONVERSATION_DOCTYPE,
		filters=[
			["modified", "<", cutoff],
			["agent_mode", "!=", AGENT_MEMORY_MODE],
			["status", "!=", ARCHIVED_STATUS],
		],
		pluck="name",
		order_by="modified asc",
		limit_page_length=limit,
	)
	return [c for c in candidates if (last_activity(c) or cutoff) < cutoff]


def _archive(conversation: str) -> dict:
	frappe.db.set_value(
		CONVERSATION_DOCTYPE, conversation, "status", ARCHIVED_STATUS, update_modified=False
	)
	return {"conversation": conversation, "action": "Archive"}


def _delete(conversation: str) -> dict:
	"""Remove the conversation and everything hanging off it.

	Children first, and by direct delete rather than through the ORM: a
	conversation can carry hundreds of messages, and running the PII, screening
	and compaction hooks over rows that are being destroyed is pure cost. Counts
	are captured BEFORE the delete so the log can say what was actually removed.
	"""
	counts = {
		"messages": frappe.db.count(MESSAGE_DOCTYPE, {"conversation": conversation}),
		"summaries": frappe.db.count(SUMMARY_DOCTYPE, {"conversation": conversation}),
	}
	frappe.db.delete(SUMMARY_DOCTYPE, {"conversation": conversation})
	frappe.db.delete(MESSAGE_DOCTYPE, {"conversation": conversation})
	frappe.db.delete(CONVERSATION_DOCTYPE, {"name": conversation})
	return {"conversation": conversation, "action": "Delete", **counts}


def sweep_expired_conversations(limit: int = SWEEP_LIMIT) -> dict:
	"""The daily pass. Returns what it did; never raises.

	A scheduled job that throws stops the whole scheduler pass, so one
	unreadable conversation must not prevent the rest being swept — each is
	handled on its own and a failure is logged and skipped.
	"""
	cfg = retention_config()
	if not cfg:
		return {"swept": 0, "action": None, "reason": "retention disabled"}

	acted: list[dict] = []
	failed: list[str] = []
	for conversation in expired_conversations(cfg["ttl_days"], limit=limit):
		try:
			acted.append(
				_delete(conversation) if cfg["action"] == "Delete" else _archive(conversation)
			)
		except Exception:
			failed.append(conversation)
			frappe.log_error(
				title="Conversation retention: could not act on a conversation",
				message=f"conversation={conversation} action={cfg['action']}\n{frappe.get_traceback()}",
			)
	frappe.db.commit()

	result = {
		"swept": len(acted),
		"failed": len(failed),
		"action": cfg["action"],
		"ttl_days": cfg["ttl_days"],
		"messages_deleted": sum(a.get("messages", 0) for a in acted),
	}
	if acted or failed:
		# The AC asks for the action to be logged. A retention policy that acts
		# silently cannot be audited, and "where did that conversation go" has
		# to have an answer.
		frappe.logger("one_bpmn").info(
			f"Conversation retention: {cfg['action']}d {len(acted)} conversation(s) "
			f"idle past {cfg['ttl_days']} days "
			f"({result['messages_deleted']} messages), {len(failed)} failed"
		)
	return result
