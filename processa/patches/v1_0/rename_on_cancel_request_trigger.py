import frappe

from processa.processa_engine.instances.listing import clear_processa_doctype_cache

OLD = "On Cancel Request"
NEW = "On Cancel"


def execute():
	"""Cancellation maps start On Cancel: rename the trigger in their start configs and diagrams."""
	frappe.db.set_value(
		"BPMN Start Event Config", {"trigger_event": OLD}, "trigger_event", NEW, update_modified=False
	)
	for model in frappe.get_all(
		"BPMN Process Model",
		filters={"bpmn_xml": ["like", f'%triggerType="{OLD}"%']},
		fields=["name", "bpmn_xml"],
	):
		frappe.db.set_value(
			"BPMN Process Model",
			model.name,
			"bpmn_xml",
			model.bpmn_xml.replace(f'triggerType="{OLD}"', f'triggerType="{NEW}"'),
			update_modified=False,
		)
	clear_processa_doctype_cache()
