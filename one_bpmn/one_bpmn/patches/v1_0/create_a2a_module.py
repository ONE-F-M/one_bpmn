import frappe


def execute():
	"""Create the A2A Module Def so the A2A doctypes can sync into it."""
	if frappe.db.exists("Module Def", "A2A"):
		return
	frappe.get_doc({"doctype": "Module Def", "module_name": "A2A", "app_name": "one_bpmn"}).insert(ignore_permissions=True)  # patch: Module Def is a system record
