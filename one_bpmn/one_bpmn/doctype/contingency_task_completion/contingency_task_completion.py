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
def get_process_doctypes(doctype, txt, searchfield, start, page_len, filters):
	"""Return DocTypes listed in the selected Process's process_doctypes child table."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)

	process_name = filters.get("process_name")
	if not process_name:
		return []

	names = frappe.get_all(
		"Process Doctype",
		filters={"parent": process_name, "parenttype": "Process"},
		fields=["document_type"],
		limit=0,
		pluck="document_type"
	)

	if not names:
		return []

	return frappe.db.sql(
		"""
		SELECT `name` FROM `tabDocType`
		WHERE `name` IN %(names)s AND `name` LIKE %(txt)s
		LIMIT {start}, {page_len}
		""".format(start=int(start), page_len=int(page_len)),
		{"names": names, "txt": f"%{txt or ''}%"},
	)


@frappe.whitelist()
def get_active_task_documents(doctype, txt, searchfield, start, page_len, filters):
	"""Return document names that have an active (Waiting) task in a BPMN Process Instance."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)

	context_doctype = filters.get("context_doctype")
	if not context_doctype:
		return []

	return frappe.db.sql(
		"""
		SELECT DISTINCT bat.target_docname
		FROM `tabBPMN Active Task` bat
		INNER JOIN `tabBPMN Process Instance` bpi ON bpi.name = bat.parent
		WHERE bat.target_doctype = %(context_doctype)s
			AND bat.parenttype = 'BPMN Process Instance'
			AND bat.status = 'Waiting'
			AND bpi.status = 'Active'
			AND bat.target_docname LIKE %(txt)s
		LIMIT {start}, {page_len}
		""".format(start=int(start), page_len=int(page_len)),
		{
			"context_doctype": context_doctype,
			"txt": f"%{txt or ''}%",
		},
	)
