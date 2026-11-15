# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
import frappe


def execute():
	"""Drop the unused is_reply column, which schema sync would leave behind."""
	if not frappe.db.has_column("Chat Message", "is_reply"):
		return
	frappe.db.sql_ddl("ALTER TABLE `tabChat Message` DROP COLUMN `is_reply`")
