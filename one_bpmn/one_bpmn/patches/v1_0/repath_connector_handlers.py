import frappe

from one_bpmn.processa_connectors.manifest import clear_manifest_cache

# Old module path to new, for the connector modules that moved into processa_connectors.
MOVED_MODULES = {
	"one_bpmn.one_bpmn.connectors.api.": "one_bpmn.api.connectors.",
	"one_bpmn.one_bpmn.connectors.agent_primitives.": "one_bpmn.processa_connectors.operations.http.",
	"one_bpmn.one_bpmn.connectors.http_ops.": "one_bpmn.processa_connectors.operations.http.",
	"one_bpmn.one_bpmn.connectors.google_docs_ops.": "one_bpmn.processa_connectors.operations.google_docs.",
	"one_bpmn.one_bpmn.connectors.google_drive_ops.": "one_bpmn.processa_connectors.operations.google_drive.",
	"one_bpmn.one_bpmn.connectors.google_slides_ops.": "one_bpmn.processa_connectors.operations.google_slides.",
	"one_bpmn.one_bpmn.connectors.manifest.": "one_bpmn.processa_connectors.manifest.",
	"one_bpmn.one_bpmn.connectors.seed.": "one_bpmn.processa_connectors.seed.",
	"one_bpmn.one_bpmn.connectors.validator.": "one_bpmn.processa_connectors.validator.",
	"one_bpmn.one_bpmn.integrations.google_common.": "one_bpmn.processa_connectors.google.common.",
	"one_bpmn.one_bpmn.integrations.google_docs.": "one_bpmn.processa_connectors.google.docs.",
	"one_bpmn.one_bpmn.integrations.google_drive.": "one_bpmn.processa_connectors.google.drive.",
	"one_bpmn.one_bpmn.integrations.google_slides.": "one_bpmn.processa_connectors.google.slides.",
	"one_bpmn.one_bpmn.integrations.retry.": "one_bpmn.processa_connectors.retry.",
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
