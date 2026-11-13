import frappe


def execute():
	"""Create the Threat Intel Module Def so the threat doctypes can sync into it."""
	if frappe.db.exists("Module Def", "Threat Intel"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "Threat Intel", "app_name": "processa"}
	).insert(ignore_permissions=True)  # perms: Module Def is a system record
