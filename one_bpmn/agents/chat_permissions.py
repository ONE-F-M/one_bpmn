# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Who may read a conversation with an agent.

Both chat doctypes granted the role ``All`` read, write, create and delete, so
any signed-in employee could list every conversation on the site through
``/api/resource`` and read what anyone had said to an agent — an unreleased
process discussed with ProsAlly, a draft leave form described to Docu. They
could edit and delete those messages too.

Scoping is done here rather than with ``if_owner`` on the permission row.
Frappe ANDs the role permission with every ``has_permission`` hook, so a hook
can narrow what a role allows but never widen it: with ``if_owner`` set, a
participant who is not the creator would be refused before this code ran. The
role keeps read and write; these hooks decide whose rows those apply to. It is
the same arrangement AI Memory already uses.

Deletion is left to System Manager alone — a conversation is the audit trail of
what an agent was asked to do.
"""

from __future__ import annotations

import frappe
from frappe.query_builder import DocType

CONVERSATION = "Chat Conversation"
MESSAGE = "Chat Message"


def _is_admin(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _visible_conversations_sql(user: str) -> str:
	"""SQL selecting the conversations ``user`` may read: the ones they started,
	plus the ones they were a participant in."""
	conversation = DocType(CONVERSATION)
	participant = DocType("Chat Participant")
	mine = (
		frappe.qb.from_(participant)
		.select(participant.parent)
		.where((participant.user == user) & (participant.parenttype == CONVERSATION))
	)
	return (
		frappe.qb.from_(conversation)
		.select(conversation.name)
		.where((conversation.owner == user) | conversation.name.isin(mine))
		.get_sql()
	)


def is_participant(conversation: str, user: str | None = None) -> bool:
	"""True when ``user`` started this conversation or took part in it."""
	user = user or frappe.session.user
	if not conversation:
		return False
	if frappe.db.get_value(CONVERSATION, conversation, "owner") == user:
		return True
	return bool(
		frappe.db.exists("Chat Participant", {"parent": conversation, "user": user, "parenttype": CONVERSATION})
	)


# ── List and report queries ────────────────────────────────────────────────


def chat_conversation_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_admin(user):
		return ""
	participant = DocType("Chat Participant")
	mine = (
		frappe.qb.from_(participant)
		.select(participant.parent)
		.where((participant.user == user) & (participant.parenttype == CONVERSATION))
		.get_sql()
	)
	safe = frappe.db.escape(user)
	return f"(`tab{CONVERSATION}`.`owner` = {safe} or `tab{CONVERSATION}`.`name` in ({mine}))"


def chat_message_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_admin(user):
		return ""
	return f"(`tab{MESSAGE}`.`conversation` in ({_visible_conversations_sql(user)}))"


# ── Document-level checks ──────────────────────────────────────────────────


def chat_conversation_has_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_admin(user):
		return True
	if ptype == "create":
		# You may always start your own; it is yours the moment it is inserted.
		return True
	if ptype in ("write", "delete", "submit", "cancel", "amend"):
		return doc.owner == user
	return is_participant(doc.name, user)


def chat_message_has_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_admin(user):
		return True

	conversation = getattr(doc, "conversation", None)
	# A message with no conversation yet is being built; the conversation link is
	# mandatory, so it is checked on the insert that follows.
	if not conversation:
		return True

	# Creating covers the agent's reply as much as the person's question: the
	# map's Save Response task runs in the asker's own session, so a reply lands
	# in a conversation they can already see.
	if ptype == "create":
		return is_participant(conversation, user)
	if ptype in ("write", "delete", "submit", "cancel", "amend"):
		return doc.owner == user and is_participant(conversation, user)
	return is_participant(conversation, user)
