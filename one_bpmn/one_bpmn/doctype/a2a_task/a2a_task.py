# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A Task — one record per protocol task, both directions (WI-001932).

Inbound: an approved client asked one of our agents for something. The
row is the ticket: wire task id, who asked (client), which agent, the
conversation/instance doing the work, and the state the caller polls.

Outbound (WI-001933): one of our processes delegated to a remote agent.
The row additionally carries the parked Spiff task, the poll schedule
and the deadline.

The delegation trace (WI-002008) lives here too — task_execution_id,
delegation_depth and handoff_count — one store, shared by the guardrail
checks and the eventual dashboard.
"""

import uuid

import frappe
from frappe.model.document import Document


class A2ATask(Document):
	def before_insert(self):
		if not self.task_id:
			self.task_id = str(uuid.uuid4())
		if not self.principal:
			self.principal = frappe.session.user
		if not self.task_execution_id:
			self.task_execution_id = str(uuid.uuid4())

	def validate(self):
		if self.state in ("completed", "canceled", "failed", "rejected", "timed-out"):
			if not self.completed_at:
				self.completed_at = frappe.utils.now_datetime()
