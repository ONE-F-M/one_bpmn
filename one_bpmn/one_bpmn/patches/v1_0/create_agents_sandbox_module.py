import frappe


def execute():
	"""Create the Agents Sandbox Module Def so the sandbox doctypes can sync into it."""
	if frappe.db.exists("Module Def", "Agents Sandbox"):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": "Agents Sandbox", "app_name": "one_bpmn"}
	).insert(ignore_permissions=True)  # patch: Module Def is a system record
