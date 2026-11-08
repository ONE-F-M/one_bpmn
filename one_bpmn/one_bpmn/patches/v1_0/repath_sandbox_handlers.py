import frappe

from one_bpmn.processa_connectors.manifest import clear_manifest_cache

# Old module path to new, for the sandbox modules that moved into agents_sandbox.
MOVED_MODULES = {
	"one_bpmn.one_bpmn.connectors.agent_sandbox_job.": "one_bpmn.agents_sandbox.sandbox.job.",
	"one_bpmn.one_bpmn.connectors.agent_sandbox_ops.": "one_bpmn.agents_sandbox.sandbox.ops.",
	"one_bpmn.one_bpmn.connectors.agent_sandbox_reaper.": "one_bpmn.agents_sandbox.sandbox.reaper.",
	"one_bpmn.one_bpmn.connectors.agent_sandbox_session.": "one_bpmn.agents_sandbox.sandbox.session.",
	"one_bpmn.one_bpmn.connectors.agent_sandbox_supervisor.": "one_bpmn.agents_sandbox.sandbox.supervisor.",
	"one_bpmn.one_bpmn.connectors.agent_sandbox_trace.": "one_bpmn.agents_sandbox.sandbox.trace.",
	"one_bpmn.one_bpmn.connectors.agent_criteria.": "one_bpmn.agents_sandbox.criteria.",
	"one_bpmn.one_bpmn.connectors.agent_reproduction.": "one_bpmn.agents_sandbox.reproduction.",
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
