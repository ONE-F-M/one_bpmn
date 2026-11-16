import frappe


def execute():
	"""Drop the Processa Comment doctype and its table; canvas comments are stored in Comment."""
	frappe.delete_doc("DocType", "Processa Comment", ignore_missing=True, force=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabProcessa Comment`")
