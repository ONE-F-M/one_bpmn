import frappe


def execute():
	"""Create the AI Agent Observability Module Def so the run, step and report records can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Observability"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Observability", "app_name": "processa"}
	).insert(ignore_permissions=True)  # perms: Module Def is a system record
