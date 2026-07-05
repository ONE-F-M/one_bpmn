import frappe


def execute():
	if not frappe.db.exists("Role", "Process Designer"):
		role = frappe.get_doc({
			"doctype": "Role",
			"role_name": "Process Designer",
			"desk_access": 1,
		})
		role.insert(ignore_permissions=True)
