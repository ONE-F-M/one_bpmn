# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A Client — the inbound guest list (WI-001931).

Every external caller is one row here. Approval provisions a dedicated
service user (the caller's badge: its API key), and ``allowed_agents`` is
the positive list of agents that badge may invoke. The A2A door resolves
``frappe.session.user`` back to this row — a caller that is not Approved
and enabled simply does not exist to the endpoint.

The user represents the CALLER, never the agent (WI-001931 revision):
per-agent traceability comes from A2A Task / AI Agent Run links.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class A2AClient(Document):
	def validate(self):
		self.validate_approval_transition()

	def validate_approval_transition(self):
		"""Stamp who approved and when; keep the stamps honest on re-approval."""
		before = self.get_doc_before_save()
		previous = before.approval_status if before else "Draft"
		if self.approval_status == "Approved" and previous != "Approved":
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		elif self.approval_status != "Approved":
			self.approved_by = None
			self.approved_on = None

	def on_update(self):
		self.sync_service_user()

	def sync_service_user(self):
		"""The service user exists exactly while the client is Approved and
		enabled. Approval creates (or re-enables) it; revoking or disabling
		the row disables it immediately — the key stops working mid-request."""
		from one_bpmn.agents.a2a.principal import (
			deactivate_client_user,
			ensure_client_user,
		)

		if self.approval_status == "Approved" and self.enabled:
			user = ensure_client_user(self)
			if self.user != user:
				self.db_set("user", user, update_modified=False)
		elif self.user:
			deactivate_client_user(self)

	def on_trash(self):
		"""Deleting the row must not leave a live badge behind."""
		from one_bpmn.agents.a2a.principal import deactivate_client_user

		if self.user:
			deactivate_client_user(self)

	@frappe.whitelist()
	def get_credentials(self) -> dict:
		"""The one sanctioned way to read this client's API credentials,
		for handing to the caller out of band. Admin only; the secret is
		decrypted at call time and never stored on this row. Explicit role
		check rather than only_for — only_for is a no-op under tests, and
		this guard must be testable."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw(
				_("Only System Managers may read A2A client credentials."),
				frappe.PermissionError,
			)
		if not self.user or self.approval_status != "Approved":
			frappe.throw(
				_("Approve the client first — credentials are issued on approval."),
				title=_("A2A Client"),
			)
		return {
			"api_key": frappe.db.get_value("User", self.user, "api_key"),
			"api_secret": frappe.utils.password.get_decrypted_password(
				"User", self.user, "api_secret"
			),
		}
