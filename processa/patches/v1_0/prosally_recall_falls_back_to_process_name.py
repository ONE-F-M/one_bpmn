"""ProsAlly's Build Context passes the process name to the memory recall as well as the diagram name.

The panel's diagram name does not always reach the turn, so recall falls back to the process name.
Edits the live Server Script by anchor; a script that already has the marker is left alone.
"""

import frappe

DASH = "–"
BUILD_CONTEXT = f"ProsAlly {DASH} Build Context"
MARKER = 'task_data.get("diagram_name", ""), task_data.get("process_name", "")'
ANCHOR = '**recall_process_memory(task_data.get("diagram_name", ""))'
REPLACEMENT = f"**recall_process_memory({MARKER})"


def add_process_name(code):
	"""The script with the process name passed to the recall, or None when the anchor is not found exactly once."""
	if code.count(ANCHOR) != 1:
		return None
	return code.replace(ANCHOR, REPLACEMENT)


def execute():
	if not frappe.db.exists("Server Script", BUILD_CONTEXT):
		return
	code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script") or ""
	if MARKER in code:
		return
	patched = add_process_name(code)
	if patched is None:
		frappe.log_error(
			title="ProsAlly recall process name: anchor not found",
			message=f"{BUILD_CONTEXT} no longer matches the text this patch edits; pass the process name by hand.",
		)
		return
	frappe.db.set_value("Server Script", BUILD_CONTEXT, "script", patched, update_modified=False)
