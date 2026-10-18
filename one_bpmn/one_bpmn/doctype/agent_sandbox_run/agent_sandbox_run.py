# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Agent Sandbox Run — one record per dispatch to the external Cloud Run
sandbox (the "AI Dev Agent" feature).

Deliberately not an A2A Task: the sandbox does not speak the A2A wire
protocol (no message/send, no remote agent card) — it is a bespoke REST
endpoint we designed ourselves. Forcing it through A2A Task's Outbound shape
would require inventing a fake "A2A Remote Agent" record for something that
isn't actually an A2A-compliant remote, so this mirrors only the parts of
that pattern that are genuinely generic: a caller pointer to resume, a
resume_enqueued guard, and a payload/result/error shape.

The row is the ticket: what was dispatched, which parked Service Task is
waiting on it, and — once the sandbox's signed callback lands — the result,
any changed files, and the PR URL once open_customization_pr() succeeds.
"""

import frappe
from frappe.model.document import Document

TERMINAL_STATES = ("completed", "failed", "stale", "timed_out", "cancelled")
ERROR_LIMIT = 2000


def bounded_error(text: str | None, limit: int = ERROR_LIMIT) -> str:
	"""The end of an error text, where the exception line is, cut from the front when too long."""
	text = (text or "").strip()
	return text if len(text) <= limit else "..." + text[-(limit - 3) :]


def identity_from_payload(request_payload) -> dict:
	"""The action, Work Item and agent a request payload carries, for the columns that make runs queryable."""
	payload = frappe.parse_json(request_payload or "{}") or {}
	found = {"action": payload.get("action"), "work_item": payload.get("work_item_id"), "agent_name": payload.get("agent_name")}
	return {field: value for field, value in found.items() if value}


class AgentSandboxRun(Document):
	def before_insert(self):
		self.started_at = self.started_at or frappe.utils.now_datetime()

	def validate(self):
		if self.state in TERMINAL_STATES and not self.completed_at:
			self.completed_at = frappe.utils.now_datetime()
		for field, value in identity_from_payload(self.request_payload).items():
			if not self.get(field):
				self.set(field, value)

	def on_update(self):
		from one_bpmn.one_bpmn.connectors.agent_sandbox_trace import sync

		sync(self)

	def db_set(self, fieldname, value=None, update_modified=True, notify=False, commit=False):
		"""Settlement writes through db_set, so the trace is refreshed here as well as on save."""
		super().db_set(fieldname, value, update_modified=update_modified, notify=notify, commit=commit)
		from one_bpmn.one_bpmn.connectors.agent_sandbox_trace import sync

		sync(self)
