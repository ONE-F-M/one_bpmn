import frappe

from processa.processa_connectors.manifest import clear_manifest_cache

# Old module path to new, for the sandbox modules that moved into agents_sandbox.
MOVED_MODULES = {
	"processa.processa.connectors.agent_sandbox_job.": "processa.agents_sandbox.sandbox.job.",
	"processa.processa.connectors.agent_sandbox_ops.": "processa.agents_sandbox.sandbox.ops.",
	"processa.processa.connectors.agent_sandbox_reaper.": "processa.agents_sandbox.sandbox.reaper.",
	"processa.processa.connectors.agent_sandbox_session.": "processa.agents_sandbox.sandbox.session.",
	"processa.processa.connectors.agent_sandbox_supervisor.": "processa.agents_sandbox.sandbox.supervisor.",
	"processa.processa.connectors.agent_sandbox_trace.": "processa.agents_sandbox.sandbox.trace.",
	"processa.processa.connectors.agent_criteria.": "processa.agents_sandbox.criteria.",
	"processa.processa.connectors.agent_reproduction.": "processa.agents_sandbox.reproduction.",
}

STORED_PATHS = (
	("BPMN Connector Operation", "handler_path"),
	("BPMN Connector Field", "value_transform"),
	("BPMN Connector Field", "choices_source_path"),
)


def execute():
	"""Point stored handler, Value Transform and Choices From paths at the moved sandbox modules."""
	for doctype, fieldname in STORED_PATHS:
		for old in MOVED_MODULES:
			for row in frappe.get_all(
				doctype, filters={fieldname: ["like", f"{old}%"]}, fields=["name", fieldname]
			):
				new = MOVED_MODULES[old] + row[fieldname][len(old) :]
				frappe.db.set_value(doctype, row.name, fieldname, new, update_modified=False)
				frappe.clear_document_cache(doctype, row.name)
	clear_manifest_cache()
