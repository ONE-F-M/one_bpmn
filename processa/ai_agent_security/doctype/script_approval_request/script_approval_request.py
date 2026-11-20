# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from processa.ai_agent_security.code_checks.script_gate import script_task_findings
from processa.ai_agent_security.code_checks.script_validator import NOT_APPROVABLE

OPEN_STATUSES = ("Pending Review", "Pending Approval")
# The name of the Approve user task on the Script Security Approval map, as its activity log records it.
APPROVE_TASK = "Approve"
READ_ALL_ROLES = {"System Manager", "Application Manager"}


class ScriptApprovalRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from processa.ai_agent_security.doctype.script_approval_request_item.script_approval_request_item import ScriptApprovalRequestItem

		approved_by: DF.Link | None
		approved_on: DF.Datetime | None
		approver: DF.Link | None
		decision_note: DF.SmallText | None
		process_name: DF.Link
		reason: DF.SmallText | None
		requested_by: DF.Link | None
		requested_items: DF.Table[ScriptApprovalRequestItem]
		reviewer: DF.Link | None
		script_at_time_of_request: DF.Code | None
		script_task: DF.Data
		script_task_label: DF.Data | None
		server_script: DF.Link
		source: DF.Literal["Requested", "Shipped by patch"]
		status: DF.Literal["Pending Review", "Pending Approval", "Approved", "Rejected"]
	# end: auto-generated types
	def before_insert(self):
		script = frappe.get_doc("Server Script", self.server_script)
		script.check_permission("read")
		self.refuse_second_open_request()
		self.set_requested_items(script.script)
		settings = frappe.get_cached_doc("Processa Settings")
		self.update(
			{
				"script_at_time_of_request": script.script,
				"reviewer": settings.script_security_reviewer,
				"approver": settings.script_security_approver,
				"requested_by": frappe.session.user,
				"status": "Pending Review",
				"source": "Requested",
				"approved_by": None,
				"approved_on": None,
			}
		)

	def validate(self):
		if not self.is_new() and self.has_value_changed("status") and not self.approved_through_the_map():
			frappe.throw(
				_("Only the Script Security Approval process changes the status of a request."),
				frappe.PermissionError,
			)

	def onload(self):
		self.set_onload("approval_started", bool(approval_instances(self.name)))

	def approved_through_the_map(self) -> bool:
		"""True when the status is Approved and the Approver completed Approve on this request's map."""
		if self.status != "Approved" or not self.approver:
			return False
		logs = frappe.get_all(
			"BPMN Activity Log",
			filters={
				"instance": ("in", approval_instances(self.name) or [""]),
				"task_name": APPROVE_TASK,
				"action": "Completed",
				"user": self.approver,
			},
			pluck="data",
		)
		return any(frappe.parse_json(data or "{}").get("action") == "Approve" for data in logs)

	def refuse_second_open_request(self):
		open_request = frappe.db.get_value(
			"Script Approval Request",
			{
				"process_name": self.process_name,
				"script_task": self.script_task,
				"server_script": self.server_script,
				"status": ("in", OPEN_STATUSES),
			},
		)
		if open_request:
			frappe.throw(
				_("Script task {0} already has an open request, {1}.").format(self.script_task, open_request)
			)

	def set_requested_items(self, code: str):
		lines = {}
		for f in script_task_findings(code, self.process_name, self.script_task, self.server_script):
			if f["category"] not in NOT_APPROVABLE:
				lines.setdefault((f["category"], f["name"], f.get("library") or ""), []).append(str(f["line"]))
		if not lines:
			frappe.throw(_("Script task {0} has nothing that needs approval.").format(self.script_task))
		self.requested_items = []
		for (category, item_name, library), numbers in lines.items():
			self.append(
				"requested_items",
				{
					"category": category,
					"item_name": item_name,
					"library": library,
					"lines": ", ".join(dict.fromkeys(numbers)),
				},
			)


def approval_instances(request_name: str) -> list:
	"""The process instances started for this request."""
	return frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "Script Approval Request", "context_docname": request_name},
		pluck="name",
	)


def get_permission_query_conditions(user: str | None = None) -> str:
	"""List only the requests the user raised, reviews or approves."""
	user = user or frappe.session.user
	if READ_ALL_ROLES & set(frappe.get_roles(user)):
		return ""
	escaped = frappe.db.escape(user)
	fields = " or ".join(
		f"`tabScript Approval Request`.`{field}` = {escaped}"
		for field in ("requested_by", "reviewer", "approver")
	)
	return f"({fields})"


def has_permission(doc, ptype=None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if READ_ALL_ROLES & set(frappe.get_roles(user)) or doc.is_new():
		return True
	return user in (doc.requested_by, doc.reviewer, doc.approver)
