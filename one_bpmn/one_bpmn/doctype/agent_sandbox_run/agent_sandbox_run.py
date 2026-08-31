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


class AgentSandboxRun(Document):
	def validate(self):
		if self.state in ("completed", "failed") and not self.completed_at:
			self.completed_at = frappe.utils.now_datetime()
