import frappe


def execute():
	"""Create the AI Agent Skills Module Def so its five skill and tool doctypes can sync into it."""
	if frappe.db.exists("Module Def", "AI Agent Skills"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "AI Agent Skills", "app_name": "processa"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
