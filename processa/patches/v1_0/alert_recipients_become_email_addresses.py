"""The two alert recipient lists hold email addresses, so each existing User row becomes that user's email.

Rows are removed once copied. Idempotent: with no rows there is nothing to do.
"""

import frappe
from frappe.utils import split_emails

DOCTYPE = "Processa Settings"
FIELDS = ("ai_health_alert_recipients", "eval_alert_recipients")


def execute():
	for field in FIELDS:
		filters = {"parenttype": DOCTYPE, "parent": DOCTYPE, "parentfield": field}
		users = frappe.get_all("User Group Member", filters=filters, pluck="user", order_by="idx asc")
		if not users:
			continue

		current = split_emails(frappe.db.get_single_value(DOCTYPE, field))
		copied = [frappe.db.get_value("User", user, "email") or user for user in users]
		frappe.db.set_single_value(DOCTYPE, field, ", ".join(dict.fromkeys(current + copied)))
		frappe.db.delete("User Group Member", filters)
