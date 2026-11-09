import frappe


def execute():
	"""Create the AI Agent Memory Module Def so its two doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Memory"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Memory", "app_name": "one_bpmn"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
