# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A Remote Agent — the outbound address book (WI-001933).

Our processes may only delegate to an entry that is enabled and
Approved: a positive allow-list, not a blocklist. The cached card is
what an approver reviews, so it must be fetched before approval, and
changing the endpoint afterwards sends the entry back to Draft — the new
address has not been reviewed.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class A2ARemoteAgent(Document):
	def validate(self):
		self.reset_approval_on_endpoint_change()
		self.require_card_before_approval()
		self.stamp_approval()

	def reset_approval_on_endpoint_change(self):
		before = self.get_doc_before_save()
		if not before or before.endpoint_url == self.endpoint_url:
			return
		if self.approval_status == "Approved" and before.approval_status == "Approved":
			self.approval_status = "Draft"
			self.agent_card = None
			self.card_fetched_at = None
			frappe.msgprint(
				_("The endpoint changed, so this entry went back to Draft. Fetch and review the card again."),
				alert=True,
			)

	def require_card_before_approval(self):
		if self.approval_status == "Approved" and not self.agent_card:
			frappe.throw(
				_("Fetch the agent card before approving — the card is what you are approving."),
				title=_("A2A Remote Agent"),
			)

	def stamp_approval(self):
		before = self.get_doc_before_save()
		previous = before.approval_status if before else "Draft"
		if self.approval_status == "Approved" and previous != "Approved":
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		elif self.approval_status != "Approved":
			self.approved_by = None
			self.approved_on = None

	@frappe.whitelist()
	def fetch_card(self) -> dict:
		"""Fetch and cache the remote's card. Allowed before approval on
		purpose: this is how an approver sees what they are approving."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only System Managers may fetch remote agent cards."), frappe.PermissionError)

		from one_bpmn.one_bpmn.integrations.a2a_client import fetch_agent_card

		card = fetch_agent_card(self)
		self.db_set(
			{
				"agent_card": frappe.as_json(card),
				"card_fetched_at": now_datetime(),
				"card_name": (card.get("name") or "")[:140],
				"card_description": (card.get("description") or "")[:500],
			},
			update_modified=True,
		)
		return card
