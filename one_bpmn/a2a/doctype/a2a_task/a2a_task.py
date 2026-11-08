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
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_configuration: DF.Link | None
		agent_run: DF.Link | None
		artifacts: DF.Code | None
		bpmn_id: DF.Data | None
		callback_token: DF.Password | None
		caller_agent_run: DF.Link | None
		caller_instance: DF.Link | None
		caller_wf_task_id: DF.Data | None
		client: DF.Link | None
		completed_at: DF.Datetime | None
		context_id: DF.Data | None
		conversation: DF.Link | None
		deadline: DF.Datetime | None
		delegated_by: DF.Link | None
		delegation_depth: DF.Int
		direction: DF.Literal["Inbound", "Outbound", "Internal"]
		error_code: DF.Data | None
		error_message: DF.SmallText | None
		handoff_count: DF.Int
		input_assignee: DF.Data | None
		input_role: DF.Link | None
		instance: DF.Link | None
		last_polled_at: DF.Datetime | None
		next_poll_at: DF.Datetime | None
		pending_human_task: DF.Data | None
		poll_attempts: DF.Int
		principal: DF.Link | None
		push_callback_token: DF.Password | None
		push_callback_url: DF.Data | None
		push_failures: DF.Int
		push_registered: DF.Check
		remote_agent: DF.Link | None
		remote_task_id: DF.Data | None
		request_payload: DF.Code | None
		result: DF.Code | None
		resume_enqueued: DF.Check
		state: DF.Literal["submitted", "working", "input-required", "completed", "canceled", "failed", "rejected", "auth-required", "timed-out"]
		status_message: DF.SmallText | None
		task_execution_id: DF.Data | None
		task_id: DF.Data | None
		wf_task_id: DF.Data | None
	# end: auto-generated types
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
