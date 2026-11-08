import frappe


def execute():
	"""Create the Processa Engine Module Def so its doctypes can sync into it."""
	if frappe.db.exists("Module Def", "Processa Engine"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "Processa Engine", "app_name": "one_bpmn"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
