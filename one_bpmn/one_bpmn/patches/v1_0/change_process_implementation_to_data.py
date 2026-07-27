import frappe


def execute():
	"""Change BPMN Process Model.process_implementation from Link to Data.

	The field used to be a Link to the Process Implementation doctype; it is
	now a plain Data field storing the same string. Both fieldtypes back onto
	a varchar column, so existing values carry over untouched — we snapshot
	them first, reload the doctype to apply the fieldtype change, then
	re-assert the values so nothing is lost regardless of how the underlying
	column migration behaves. Idempotent.
	"""
	rows = frappe.db.get_all(
		"BPMN Process Model",
		filters={"process_implementation": ["is", "set"]},
		fields=["name", "process_implementation"],
	)

	# Apply the Link -> Data fieldtype change.
	frappe.reload_doc("one_bpmn", "doctype", "bpmn_process_model")

	# Re-assert the previous values (no-op when the column migration preserved them).
	for r in rows:
		frappe.db.set_value(
			"BPMN Process Model",
			r.name,
			"process_implementation",
			r.process_implementation,
			update_modified=False,
		)
