# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
AI Security Event — the one place a screening verdict is recorded (WI-001967).

Append-only by construction. The doctype grants create and read but no write and
no delete, and the controller enforces the same thing a second time, because a
permission grant is not a guarantee: Administrator bypasses permissions, and
``ignore_permissions=True`` is one keyword away in any calling code. Controller
hooks run regardless, so the rules below are what actually make the record
immutable.

The raw screened content is never stored. What is kept is a SHA-256 of it plus a
length, which is enough to recognise the same input twice, group repeats, and
prove an event refers to a specific message — without the record itself becoming
a copy of the thing it was protecting.
"""

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# Boundaries a verdict can be reached at, mirroring the Select options.
BOUNDARIES = ("input", "output", "tool-result", "memory-write")
ACTIONS = ("Log", "Flag", "Block")


def content_hash(content) -> str:
	"""SHA-256 of the screened content, or "" when there was none.

	Stable across processes (no salt) on purpose: the same message screened twice
	must produce the same hash, otherwise repeats cannot be grouped and an event
	cannot be tied back to the message a reviewer is looking at.
	"""
	if content is None:
		return ""
	text = content if isinstance(content, str) else str(content)
	if not text:
		return ""
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AISecurityEvent(Document):
	def before_insert(self):
		self.detected_at = self.detected_at or now_datetime()

	def validate(self):
		self._reject_update()
		self._validate_enums()

	def on_update(self):
		# Frappe runs on_update after an insert as well as after a save, and by
		# that point is_new() is already False — so this must exempt the insert
		# explicitly or the very first write rejects itself. Kept alongside
		# validate() because a save with ignore_validate would skip that one.
		if self.flags.in_insert:
			return
		self._reject_update()

	def on_trash(self):
		frappe.throw(
			_(
				"AI Security Events cannot be deleted. The audit trail is the point of "
				"the record — if an event is wrong, record the correction, do not remove "
				"the evidence."
			),
			title=_("Immutable Record"),
		)

	def _reject_update(self):
		if self.is_new():
			return
		frappe.throw(
			_(
				"AI Security Events cannot be edited once recorded. This applies to every "
				"role, including System Manager — an audit log that can be rewritten is "
				"not an audit log."
			),
			title=_("Immutable Record"),
		)

	def _validate_enums(self):
		if self.boundary not in BOUNDARIES:
			frappe.throw(
				_("Boundary must be one of: {0}").format(", ".join(BOUNDARIES)),
				title=_("Invalid Boundary"),
			)
		if self.action not in ACTIONS:
			frappe.throw(
				_("Action must be one of: {0}").format(", ".join(ACTIONS)),
				title=_("Invalid Action"),
			)
