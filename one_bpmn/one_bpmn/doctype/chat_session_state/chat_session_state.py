# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChatSessionState(Document):
	def validate(self):
		self._reject_duplicate_keys()

	def _reject_duplicate_keys(self):
		"""Two rows with the same key make the scratchpad ambiguous.

		Reading builds a dict, so a duplicate would silently resolve to whichever
		row came last — a value that changes with row order rather than with what
		anybody wrote. The write path cannot produce this (it merges through a
		dict), so a duplicate means a hand edit in Desk, and saying so beats
		letting a reader guess.
		"""
		seen = set()
		for row in self.entries or []:
			key = (row.key or "").strip()
			if not key:
				frappe.throw(_("A session state entry needs a key."))
			if key in seen:
				frappe.throw(_("Duplicate session state key: {0}").format(key))
			seen.add(key)
