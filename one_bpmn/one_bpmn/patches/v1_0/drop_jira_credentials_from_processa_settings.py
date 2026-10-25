"""Delete the stored Jira URL, email and API token of Processa Settings."""

import frappe

FIELDS = ("jira_url", "jira_email", "jira_api_token")


def execute():
	frappe.db.delete("Singles", {"doctype": "Processa Settings", "field": ["in", FIELDS]})
	frappe.db.delete("__Auth", {"doctype": "Processa Settings", "fieldname": "jira_api_token"})
