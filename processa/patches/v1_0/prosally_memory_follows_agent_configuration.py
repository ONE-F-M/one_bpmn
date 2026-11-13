"""ProsAlly's process memory is switched on and off from its AI Agent Configuration.

The agent keeps Long-Term Memory Enabled, Entity scope and distilled writes, and Build Context sets
blank memory keys so the orchestrator task skips memory and nothing is used twice. A script that
already has the marker is left alone.
"""

import frappe

DASH = "–"
AGENT_ID = "prosally_agent"
BUILD_CONTEXT = f"ProsAlly {DASH} Build Context"
MARKER = "memory_reference_name"
ANCHOR = "# The AI Agent Task does tool-calling internally"
BLANK_KEYS = 'result["memory_reference_doctype"] = ""\nresult["memory_reference_name"] = ""\n\n'
TOKEN_BUDGET = 800
SETTINGS = {"long_term_memory": "Enabled", "memory_scope": "Entity", "memory_write_mode": "distilled"}


def add_blank_keys(code):
	"""The script with the blank memory keys added, or None when the anchor is not found exactly once."""
	if code.count(ANCHOR) != 1:
		return None
	return code.replace(ANCHOR, BLANK_KEYS + ANCHOR)


def execute():
	if frappe.db.exists("Server Script", BUILD_CONTEXT):
		code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script") or ""
		if MARKER not in code:
			patched = add_blank_keys(code)
			if patched is None:
				frappe.log_error(
					title="ProsAlly memory keys: anchor not found",
					message=f"{BUILD_CONTEXT} no longer matches the text this patch edits; add the keys by hand.",
				)
			else:
				frappe.db.set_value("Server Script", BUILD_CONTEXT, "script", patched, update_modified=False)

	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if config:
		values = dict(SETTINGS)
		if not frappe.db.get_value("AI Agent Configuration", config, "memory_token_budget"):
			values["memory_token_budget"] = TOKEN_BUDGET
		frappe.db.set_value("AI Agent Configuration", config, values)
