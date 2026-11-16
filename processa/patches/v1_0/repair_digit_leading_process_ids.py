"""A process id that starts with a digit is not a legal XML id: the editor drops the process and draws a collapsed pool.

Every such id gains a letter prefix, in the record, in its diagram and in every Call Activity that names it.
"""

import frappe

from processa.processa_engine.doctype.bpmn_process_model.bpmn_process_model import swap_process_id


def execute():
	models = frappe.get_all("BPMN Process Model", fields=["name", "process_id", "is_active"])
	for model in models:
		old_id = model.process_id
		if not old_id[:1].isdigit():
			continue
		new_id = "p_" + old_id
		xml = frappe.db.get_value("BPMN Process Model", model.name, "bpmn_xml") or ""
		frappe.db.set_value(
			"BPMN Process Model",
			model.name,
			{"process_id": new_id, "bpmn_xml": swap_process_id(xml, old_id, new_id)},
			update_modified=False,
		)
		for caller in frappe.get_all(
			"BPMN Process Model",
			filters={"name": ["!=", model.name], "bpmn_xml": ["like", f'%calledElement="{old_id}"%']},
			pluck="name",
		):
			caller_xml = frappe.db.get_value("BPMN Process Model", caller, "bpmn_xml") or ""
			frappe.db.set_value(
				"BPMN Process Model",
				caller,
				"bpmn_xml",
				swap_process_id(caller_xml, old_id, new_id),
				update_modified=False,
			)
		if model.is_active:
			frappe.log_error(
				title="repair_digit_leading_process_ids: active model renamed",
				message=f"{model.name}: {old_id} is now {new_id}; deploy it again so the compiled map follows.",
			)
