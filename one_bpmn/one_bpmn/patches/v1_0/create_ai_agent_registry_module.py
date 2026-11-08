import frappe


def execute():
	"""Create the AI Agent Registry Module Def so the agent configuration doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Registry"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Registry", "app_name": "one_bpmn"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
