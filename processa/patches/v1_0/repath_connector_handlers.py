import frappe

from processa.processa_connectors.manifest import clear_manifest_cache

# Old module path to new, for the connector modules that moved into processa_connectors.
MOVED_MODULES = {
	"processa.processa.connectors.api.": "processa.api.connectors.",
	"processa.processa.connectors.agent_primitives.": "processa.processa_connectors.operations.http.",
	"processa.processa.connectors.http_ops.": "processa.processa_connectors.operations.http.",
	"processa.processa.connectors.google_docs_ops.": "processa.processa_connectors.operations.google_docs.",
	"processa.processa.connectors.google_drive_ops.": "processa.processa_connectors.operations.google_drive.",
	"processa.processa.connectors.google_slides_ops.": "processa.processa_connectors.operations.google_slides.",
	"processa.processa.connectors.manifest.": "processa.processa_connectors.manifest.",
	"processa.processa.connectors.seed.": "processa.processa_connectors.seed.",
	"processa.processa.connectors.validator.": "processa.processa_connectors.validator.",
	"processa.processa.integrations.google_common.": "processa.processa_connectors.google.common.",
	"processa.processa.integrations.google_docs.": "processa.processa_connectors.google.docs.",
	"processa.processa.integrations.google_drive.": "processa.processa_connectors.google.drive.",
	"processa.processa.integrations.google_slides.": "processa.processa_connectors.google.slides.",
	"processa.processa.integrations.retry.": "processa.processa_connectors.retry.",
}

STORED_PATHS = (
	("BPMN Connector Operation", "handler_path"),
	("BPMN Connector Field", "value_transform"),
	("BPMN Connector Field", "choices_source_path"),
)


def execute():
	"""Point stored handler, Value Transform and Choices From paths at the moved connector modules."""
	for doctype, fieldname in STORED_PATHS:
		for old in MOVED_MODULES:
			for row in frappe.get_all(
				doctype, filters={fieldname: ["like", f"{old}%"]}, fields=["name", fieldname]
			):
				new = MOVED_MODULES[old] + row[fieldname][len(old) :]
				frappe.db.set_value(doctype, row.name, fieldname, new, update_modified=False)
				frappe.clear_document_cache(doctype, row.name)
	clear_manifest_cache()
