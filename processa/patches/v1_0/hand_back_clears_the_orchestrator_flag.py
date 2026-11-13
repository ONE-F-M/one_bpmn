"""The Hand Back to a Person tool clears the orchestrator flag instead of setting it."""

import frappe

SCRIPT = "Work Item Tool: Hand Back to a Person"
WRONG = "item.orchestrator = 1\n"
RIGHT = "item.orchestrator = 0\n"


def execute():
	if not frappe.db.exists("Server Script", SCRIPT):
		return
	script = frappe.db.get_value("Server Script", SCRIPT, "script") or ""
	if WRONG in script:
		frappe.db.set_value("Server Script", SCRIPT, "script", script.replace(WRONG, RIGHT, 1))
