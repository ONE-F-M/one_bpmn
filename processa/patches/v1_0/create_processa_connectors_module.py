import frappe


def execute():
	"""Create the Processa Connectors Module Def so the connector doctypes can sync into it."""
	if frappe.db.exists("Module Def", "Processa Connectors"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "Processa Connectors", "app_name": "processa"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
