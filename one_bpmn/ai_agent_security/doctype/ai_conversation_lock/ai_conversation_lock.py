# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
AI Conversation Lock — a frozen conversation and the record of why.

Created automatically when a user accumulates blocked attempts against an agent.
While one is Locked every further message on that conversation is refused at the
invocation entry point.

RELEASE IS A REVIEWER'S DECISION
--------------------------------
A lock is not self-service. The doctype grants no write to anyone, so the only
route out is :func:`one_bpmn.api.security.release_lock`, which checks
the reviewer roles and — the part that actually matters — refuses to let the
locked user release their own lock, whatever roles they happen to hold. A
containment control someone can lift on themselves contains nothing.

The record itself is kept after release rather than deleted: "this user was
frozen twice last month and talked their way out both times" is exactly the
pattern a reviewer needs to see.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class AIConversationLock(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_configuration: DF.Link | None
		blocked_count: DF.Int
		conversation: DF.Data | None
		detail: DF.SmallText | None
		locked_at: DF.Datetime | None
		reason: DF.Literal["Repeated Blocked Attempts", "Rate Limit", "Manual"]
		release_notes: DF.SmallText | None
		released_at: DF.Datetime | None
		released_by: DF.Link | None
		status: DF.Literal["Locked", "Released"]
		trigger_event: DF.Link | None
		user: DF.Link
	# end: auto-generated types
	def before_insert(self):
		self.locked_at = self.locked_at or now_datetime()
		self.status = self.status or "Locked"

	def on_trash(self):
		frappe.throw(
			_(
				"Conversation locks cannot be deleted — the history of who was frozen, "
				"and who let them back in, is the point of the record. Release it instead."
			),
			title=_("Immutable Record"),
		)


def active_lock(user: str, agent_configuration: str | None = None, conversation: str | None = None):
	"""The Locked record covering this turn, or None.

	A lock is matched on the conversation when it has one, and otherwise on the
	user/agent pair — a freeze raised before a conversation existed must still
	bite on the next attempt, or the user simply starts a new chat and carries on.

	Never raises: an unreadable lock table must not take down every conversation
	on the site. It fails OPEN, unlike the check it guards, because the failure
	mode of the alternative is a total outage from a transient DB blip.
	"""
	try:
		if conversation:
			hit = frappe.db.get_value(
				"AI Conversation Lock", {"conversation": conversation, "status": "Locked"}, "name"
			)
			if hit:
				return hit
		filters = {"user": user, "status": "Locked"}
		if agent_configuration:
			filters["agent_configuration"] = agent_configuration
		return frappe.db.get_value("AI Conversation Lock", filters, "name")
	except Exception:
		frappe.log_error(
			title="AI Conversation Lock: lookup failed — turn allowed through",
			message=frappe.get_traceback(),
		)
		return None
