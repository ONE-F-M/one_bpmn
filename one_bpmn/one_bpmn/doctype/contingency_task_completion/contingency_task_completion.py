# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ContingencyTaskCompletion(Document):
	def before_insert(self):
		if not self.process_owner:
			employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
			if employee:
				self.process_owner = employee




@frappe.whitelist()
def get_process_doctypes(
	doctype: str,
	txt: str,
	searchfield: str,
	start: int,
	page_len: int,
	filters: dict | str | None,
) -> list[str]:
	"""Return DocTypes listed in the selected Process's process_doctypes child table."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)

	filters = filters or {}
	process_name = filters.get("process_name")
	if not process_name:
		return []

	if not frappe.db.exists("Process", process_name):
		return []

	frappe.get_doc("Process", process_name).check_permission("read")

	names = frappe.get_all(
		"Process Doctype",
		filters={"parent": process_name, "parenttype": "Process"},
		fields=["document_type"],
		limit=0,
		pluck="document_type",
	)

	if not names:
		return []

	return frappe.get_all(
		"DocType",
		filters=[
			["name", "in", names],
			["name", "like", f"%{txt or ''}%"],
		],
		fields=["name"],
		start=int(start),
		page_length=int(page_len),
		pluck="name",
	)


@frappe.whitelist()
def get_active_task_documents(
	doctype: str,
	txt: str,
	searchfield: str,
	start: int,
	page_len: int,
	filters: dict | str | None = None,
):
	"""Return readable document names with waiting tasks for the selected process and context DocType."""
	filters = frappe.parse_json(filters) if isinstance(filters, str) else filters or {}

	process_name = filters.get("process_name")
	context_doctype = filters.get("context_doctype")
	if not process_name or not context_doctype:
		return []

	process_models = frappe.get_all(
		"BPMN Process Model",
		filters={"process_name": process_name},
		pluck="name",
		limit_page_length=0,
	)
	if not process_models:
		return []

	active_instances = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"status": "Active",
			"process_model": ["in", process_models],
		},
		pluck="name",
		limit_page_length=0,
	)
	if not active_instances:
		return []

	task_rows = frappe.get_all(
		"BPMN Active Task",
		filters={
			"parent": ["in", active_instances],
			"parenttype": "BPMN Process Instance",
			"status": "Waiting",
			"target_doctype": context_doctype,
			"target_docname": ["like", f"%{txt or ''}%"],
		},
		fields=["target_docname"],
		group_by="target_docname",
		order_by="target_docname asc",
		limit_page_length=0,
	)

	readable_docnames = [
		row.target_docname
		for row in task_rows
		if frappe.has_permission(context_doctype, ptype="read", doc=row.target_docname)
	]

	return readable_docnames[int(start) : int(start) + int(page_len)]
