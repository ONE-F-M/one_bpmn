import frappe

def execute():
	if not frappe.db.exists("Role", "Process Owner"):
		role = frappe.get_doc({
			"doctype": "Role",
			"role_name": "Process Owner",
			"desk_access": 1
		})
		role.insert(ignore_permissions=True)
