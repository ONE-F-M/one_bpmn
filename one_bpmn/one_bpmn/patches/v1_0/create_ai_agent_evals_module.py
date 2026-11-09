import frappe


def execute():
	"""Create the AI Agent Evals Module Def so the eval doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Evals"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Evals", "app_name": "one_bpmn"}
	).insert(ignore_permissions=True)  # perms: Module Def is a system record
