import frappe


def execute():
	"""Create the AI Agent Conversations Module Def so its seven doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Conversations"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Conversations", "app_name": "processa"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
