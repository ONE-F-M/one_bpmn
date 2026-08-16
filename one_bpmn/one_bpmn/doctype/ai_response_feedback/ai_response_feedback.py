# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One user's verdict on one agent reply (WI-001641)."""

import frappe
from frappe import _
from frappe.model.document import Document


class AIResponseFeedback(Document):
	def validate(self):
		# One person, one reply, one rating. The unique index on dedup_key is what
		# actually enforces it — a check-then-insert would race two clicks against
		# each other and leave the same reply rated twice by the same user.
		if not (self.message and self.rated_by):
			frappe.throw(_("Feedback needs both a message and a rater."))
		self.dedup_key = f"{self.message}|{self.rated_by}"

		if not self.rated_on:
			self.rated_on = frappe.utils.now_datetime()

		# Reasons only ever qualify a complaint. Keeping them off a positive
		# rating stops "Inaccurate" turning up on a thumbs up when someone
		# re-rates from down to up without the panel clearing the chips.
		if self.rating == "Positive" and self.reasons:
			self.reasons = []

		seen = set()
		kept = []
		for row in self.reasons or []:
			if row.reason and row.reason not in seen:
				seen.add(row.reason)
				kept.append(row)
		self.reasons = kept
