"""Logix's map Server Script functions: the script under debug and its last error for Build Context."""

import re

import frappe

CODE_FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)
TRACEBACK = "Traceback (most recent call last)"
ERROR_CHARS = 3000
ENGINE_ERROR_TITLE = 'BPMN ScriptTask: "{}" execution failed'


def debug_inputs(user_text: str, original_script_content: str, current_script: str) -> dict:
	"""The script under debug and its last error; what the person pasted wins over the linked script."""
	user_text = user_text or ""
	script_text = original_script_content or ""
	for block in CODE_FENCE.findall(user_text):
		if TRACEBACK not in block:
			script_text = block.strip()
			break

	at = user_text.find(TRACEBACK)
	last_error = user_text[at:] if at != -1 else _logged_error(current_script)
	return {"script_text": script_text, "last_error": last_error[-ERROR_CHARS:]}


def _logged_error(script_name: str) -> str:
	if not script_name:
		return ""
	rows = frappe.get_all(
		"Error Log",
		filters={"method": ENGINE_ERROR_TITLE.format(script_name)},
		fields=["error"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0].error if rows else ""
