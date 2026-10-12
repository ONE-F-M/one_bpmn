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

		if self.is_new():
			self.validate_snapshot()
			self.set_process_owner()
			self.set_run_errors()

		# Negative feedback with no comment tells a Process Owner nothing they
		# can act on. Enforced here too, behind the API-level check in
		# api/feedback.py — never trust the client alone.
		if self.rating == "Negative" and not (self.comment or "").strip():
			frappe.throw(_("A comment is required when rating a reply Negative."))

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

	def validate_snapshot(self):
		"""A new record carries the reply text, and the question when a user turn preceded the reply."""
		if not (self.output or "").strip():
			frappe.throw(_("Feedback needs the text of the reply it rates."))
		if (self.user_message or "").strip():
			return
		msg = frappe.db.get_value("Chat Message", self.message, ["conversation", "creation"], as_dict=True)
		if frappe.db.exists(
			"Chat Message",
			{"conversation": msg.conversation, "message_type": "User", "creation": ["<=", msg.creation]},
		):
			frappe.throw(_("Feedback needs the user message the reply answered."))

	def set_process_owner(self):
		"""Assign the record to the agent's Feedback Owner, or its Process Owner when none is set."""
		if not self.agent_configuration:
			return
		owners = frappe.db.get_value(
			"AI Agent Configuration",
			self.agent_configuration,
			["feedback_owner", "process_owner"],
			as_dict=True,
		)
		self.process_owner = owners.feedback_owner or owners.process_owner

	def set_run_errors(self):
		"""Copy each failed tool call of the linked run as one "tool: error" line."""
		if not self.agent_run:
			return
		step = frappe.qb.DocType("AI Agent Step")
		call = frappe.qb.DocType("AI Agent Tool Call")
		rows = (
			frappe.qb.from_(call)
			.join(step)
			.on(call.parent == step.name)
			.select(call.tool_name, call.tool_result)
			.where(call.parenttype == "AI Agent Step")
			.where(step.run == self.agent_run)
			.where(call.status.isin(("Error", "Denied")))
			.orderby(step.step_index)
			.orderby(call.idx)
		).run(as_dict=True)
		self.run_errors = "\n".join(f"{r.tool_name}: {(r.tool_result or '').strip()}" for r in rows)
