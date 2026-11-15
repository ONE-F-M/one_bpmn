import frappe


def execute():
	"""Create the AI Agent Guardrails Module Def so its four doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Guardrails"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Guardrails", "app_name": "processa"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
