import frappe


def execute():
	"""Create the AI Agent Security Module Def so its three doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Security"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Security", "app_name": "one_bpmn"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
