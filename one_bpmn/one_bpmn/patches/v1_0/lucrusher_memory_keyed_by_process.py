"""LuCrusher keeps long-term memory per confirmed business Process.

Build Context sets memory_reference_doctype and memory_reference_name from the
confirmed process (blank until one is confirmed), and the agent moves to Entity scope.
Edits the live Server Script by anchor; a target that already has the marker is left alone.
"""

import frappe

DASH = "\u2013"
BUILD_CONTEXT = f"LuCrusher {DASH} Build Context"
AGENT_ID = "lucrusher"
MARKER = "memory_reference_name"
ANCHOR = "set_turn(conversation_id, {"
KEYS_BLOCK = '''_cp = context_state.get("confirmed_process")
_cp_name = (_cp.get("name") or _cp.get("process_name")) if isinstance(_cp, dict) else _cp
_cp_ok = bool(_cp_name) and bool(frappe.db.exists("Process", _cp_name))
result["memory_reference_doctype"] = "Process" if _cp_ok else ""
result["memory_reference_name"] = _cp_name if _cp_ok else ""

'''


def add_keys(code):
	"""The script with the memory keys block added, or None when the anchor is not found exactly once."""
	if code.count(ANCHOR) != 1:
		return None
	return code.replace(ANCHOR, KEYS_BLOCK + ANCHOR)


def execute():
	if frappe.db.exists("Server Script", BUILD_CONTEXT):
		code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script") or ""
		if MARKER not in code:
			patched = add_keys(code)
			if patched is None:
				frappe.log_error(
					title="LuCrusher memory keys: anchor not found",
					message=f"{BUILD_CONTEXT} no longer matches the text this patch edits; add the keys by hand.",
				)
			else:
				frappe.db.set_value("Server Script", BUILD_CONTEXT, "script", patched, update_modified=False)

	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if config:
		frappe.db.set_value("AI Agent Configuration", config, "memory_scope", "Entity")
