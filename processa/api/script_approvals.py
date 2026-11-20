"""The Logix calls for script security: each finding with its approval state, and raising a request."""

import frappe
from frappe import _

from processa.ai_agent_security.code_checks.script_gate import lint_script
from processa.ai_agent_security.doctype.script_approval_request.script_approval_request import (
	approval_instances,
)
from processa.processa_engine.triggers import on_doc_event


@frappe.whitelist()
def lint_server_script(
	code: str = "", script_name: str = "", process: str = "", script_task: str = ""
) -> dict:
	"""Each finding in the code with its category, line and approval state, and the script task's status."""
	result = lint_script(code, script_name, process, script_task)
	result["violations"] = [f["message"] for f in result["findings"] if not f["approved"]]
	result["valid"] = not result["violations"]
	return result


@frappe.whitelist(methods=["POST"])
def request_script_approval(
	server_script: str, process: str, script_task: str, reason: str = "", script_task_label: str = ""
) -> dict:
	"""Raise a Script Approval Request for one script task from its saved Server Script."""
	frappe.get_doc("Server Script", server_script).check_permission("write")
	if not (reason or "").strip():
		frappe.throw(_("Say why this script needs the items it uses."))
	request = frappe.get_doc(
		{
			"doctype": "Script Approval Request",
			"process_name": process,
			"script_task": script_task,
			"script_task_label": script_task_label,
			"server_script": server_script,
			"reason": reason.strip(),
		}
	).insert()
	return {"name": request.name, "status": request.status}


@frappe.whitelist(methods=["POST"])
def retry_script_approval(request: str) -> dict:
	"""Start the Script Security Approval process for a request whose start did not happen."""
	doc = frappe.get_doc("Script Approval Request", request)
	doc.check_permission("read")
	if not approval_instances(doc.name):
		on_doc_event(doc, "after_insert")
	return {"started": bool(approval_instances(doc.name))}
