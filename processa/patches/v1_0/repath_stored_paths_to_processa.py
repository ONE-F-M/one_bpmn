import frappe

from processa.processa_connectors.manifest import clear_manifest_cache

OLD_PREFIX = "one_bpmn."
NEW_PREFIX = "processa."

STORED_PATHS = (
	("BPMN Connector Operation", "handler_path"),
	("BPMN Connector Field", "value_transform"),
	("BPMN Connector Field", "choices_source_path"),
)


def execute():
	"""Point stored handler, Value Transform and Choices From paths at the processa package."""
	for doctype, fieldname in STORED_PATHS:
		for row in frappe.get_all(
			doctype, filters={fieldname: ["like", f"{OLD_PREFIX}%"]}, fields=["name", fieldname]
		):
			new = NEW_PREFIX + row[fieldname][len(OLD_PREFIX) :]
			frappe.db.set_value(doctype, row.name, fieldname, new, update_modified=False)
			frappe.clear_document_cache(doctype, row.name)
	clear_manifest_cache()
