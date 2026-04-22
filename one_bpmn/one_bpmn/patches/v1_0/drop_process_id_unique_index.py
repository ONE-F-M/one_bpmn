import frappe


def execute():
	"""Drop the unique index on process_id in BPMN Process Model.

	The process_id field (e.g. 'Process_1') is an internal BPMN identifier
	extracted from the XML. Multiple models legitimately share the same
	default Process_1 ID. The unique constraint was removed from the DocType
	JSON, but Frappe does not reliably drop unique indexes during schema sync.
	This patch ensures the index is dropped explicitly.
	"""
	table = "tabBPMN Process Model"
	if frappe.db.has_index(table, "process_id"):
		frappe.db.sql_ddl("ALTER TABLE `tabBPMN Process Model` DROP INDEX `process_id`")
