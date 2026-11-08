import frappe

from one_bpmn.processa_connectors.manifest import clear_manifest_cache

OLD_MODULE = "one_bpmn.one_bpmn.connectors.a2a_client_ops."
NEW_MODULE = "one_bpmn.a2a.client_ops."

STORED_PATHS = (
	("BPMN Connector Operation", "handler_path"),
	("BPMN Connector Field", "choices_source_path"),
)


def execute():
	"""Point stored A2A handler and Choices From paths at one_bpmn.a2a.client_ops."""
	for doctype, fieldname in STORED_PATHS:
		for row in frappe.get_all(
			doctype, filters={fieldname: ["like", f"{OLD_MODULE}%"]}, fields=["name", fieldname]
		):
			new = NEW_MODULE + row[fieldname][len(OLD_MODULE) :]
			frappe.db.set_value(doctype, row.name, fieldname, new, update_modified=False)
			frappe.clear_document_cache(doctype, row.name)
	clear_manifest_cache()
