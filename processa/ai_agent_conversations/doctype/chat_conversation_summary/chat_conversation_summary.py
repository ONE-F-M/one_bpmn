# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChatConversationSummary(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_id: DF.Data | None
		conversation: DF.Link
		covered_count: DF.Int
		covered_from: DF.Link | None
		covered_to: DF.Link | None
		covered_upto: DF.Datetime
		generated_on: DF.Datetime | None
		model: DF.Data | None
		provider: DF.Data | None
		summary: DF.LongText
		supersedes: DF.Link | None
	# end: auto-generated types
	def validate(self):
		self._require_a_covered_range()
		self._reject_a_foreign_chain()

	def _require_a_covered_range(self):
		"""A summary with no covered range is unreadable and unsafe.

		``covered_upto`` is the cursor the read path filters on, and
		``covered_count`` is what tells a reader how much prose stands behind
		the summary. A record missing either would silently cover nothing (so
		the whole history is re-sent, defeating the point) or cover everything
		(so recent turns vanish).
		"""
		if not self.covered_upto:
			frappe.throw(_("A conversation summary must record the point it covers up to."))
		if not (self.covered_count and self.covered_count > 0):
			frappe.throw(_("A conversation summary must cover at least one message."))

	def _reject_a_foreign_chain(self):
		"""``supersedes`` must point at a summary of the SAME conversation.

		The read path takes the newest summary for a conversation and trusts its
		cursor. A chain that crossed conversations would let one conversation's
		cursor hide another's messages, which is the one failure mode here that
		loses user-visible content rather than merely wasting tokens.
		"""
		if not self.supersedes:
			return
		parent_conversation = frappe.db.get_value(
			"Chat Conversation Summary", self.supersedes, "conversation"
		)
		if parent_conversation and parent_conversation != self.conversation:
			frappe.throw(
				_("A summary can only supersede another summary of the same conversation.")
			)


def on_doctype_update():
	"""Index the read path's query shape.

	Every read is "the newest summary for this conversation", i.e. filter on
	``conversation`` and order by ``covered_upto`` descending — so the two
	belong in one composite index rather than two single-column ones.
	``add_index`` is idempotent.
	"""
	frappe.db.add_index("Chat Conversation Summary", ["conversation", "covered_upto"])
