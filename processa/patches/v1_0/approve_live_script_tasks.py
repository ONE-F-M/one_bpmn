import frappe
from frappe import _
from frappe.utils import now_datetime

from processa.ai_agent_security.code_checks.script_gate import script_task_sources
from processa.ai_agent_security.code_checks.script_validator import SYNTAX_ERROR, inspect_script


def execute():
	"""Approve, for each script task on an active map, what its Server Script uses today."""
	for model in frappe.get_all(
		"BPMN Process Model", filters={"is_active": 1}, fields=["name", "process_name", "bpmn_xml"]
	):
		if not model.process_name:
			print(f"Skipped map {model.name}: it has no Process, so its script tasks cannot be approved.")
			continue
		for label, code, allowed, bpmn_id, server_script in script_task_sources(
			model.bpmn_xml, model.process_name
		):
			findings = [f for f in inspect_script(code, allowed) if f["category"] != SYNTAX_ERROR]
			if server_script and findings:
				approve(model.process_name, bpmn_id, label, server_script)
	for name in awaiting_review():
		print(f"Server Script {name} was awaiting review and stays disabled.")


def approve(process: str, script_task: str, label: str, server_script: str) -> None:
	request = frappe.get_doc(
		{
			"doctype": "Script Approval Request",
			"process_name": process,
			"script_task": script_task,
			"script_task_label": label,
			"server_script": server_script,
			"reason": _("Used by the live map when script approval was introduced."),
		}
	).insert()
	request.db_set(
		{
			"status": "Approved",
			"source": "Shipped by patch",
			"approved_by": "Administrator",
			"approved_on": now_datetime(),
		}
	)


def awaiting_review() -> list:
	if not frappe.db.has_column("Server Script", "processa_pending_review"):
		return []
	return frappe.get_all(
		"Server Script", filters={"processa_pending_review": 1, "disabled": 1}, pluck="name", order_by="name"
	)
