"""Logix's map Server Script functions: the script under debug, its last error and the library scripts on the map."""

import ast
import re
import xml.etree.ElementTree as ET

import frappe
from frappe.utils.safe_exec import SERVER_SCRIPT_FILE_PREFIX

CODE_FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)
TRACEBACK = "Traceback (most recent call last)"
ERROR_CHARS = 3000
ENGINE_ERROR_TITLE = 'BPMN ScriptTask: "{}" execution failed'
CHECK_ERROR_TITLE = 'Logix check: "{}" failed'
BPMN_NS = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
SERVER_SCRIPT_ATTR = "{http://spiffworkflow.org/bpmn/schema/1.0/core}serverScript"


def debug_inputs(user_text: str, original_script_content: str, current_script: str) -> dict:
	"""The script under debug and its newest error; what the person pasted wins over the saved script."""
	user_text = user_text or ""
	script_text = _saved_script(current_script) or original_script_content or ""
	for block in CODE_FENCE.findall(user_text):
		if TRACEBACK not in block:
			script_text = block.strip()
			break

	at = user_text.find(TRACEBACK)
	last_error = user_text[at:][-ERROR_CHARS:] if at != -1 else _logged_error(current_script)
	return {"script_text": script_text, "last_error": last_error}


def _saved_script(script_name: str) -> str:
	return (script_name and frappe.db.get_value("Server Script", script_name, "script")) or ""


def _logged_error(script_name: str) -> str:
	"""The newest Error Log raised by this script, whichever path ran it, with when it and the script were saved."""
	if not script_name:
		return ""
	rows = frappe.get_all(
		"Error Log",
		or_filters=[
			["method", "=", ENGINE_ERROR_TITLE.format(script_name)],
			["method", "=", CHECK_ERROR_TITLE.format(script_name)],
			["error", "like", f'%{SERVER_SCRIPT_FILE_PREFIX}: {frappe.scrub(script_name)}"%'],
		],
		fields=["error", "creation"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return ""
	saved = frappe.db.get_value("Server Script", script_name, "modified")
	return f"Logged {rows[0].creation}; the script was last saved {saved}.\n{rows[0].error[-ERROR_CHARS:]}"


def library_scripts(process_model: str | None) -> list[dict]:
	"""The library scripts on a map that the user can read, each with its function signatures.

	A library is a script task with no incoming or outgoing flow whose script only defines functions.
	"""
	bpmn_xml = process_model and frappe.db.get_value("BPMN Process Model", process_model, "bpmn_xml")
	if not bpmn_xml:
		return []
	libraries = []
	for task in ET.fromstring(bpmn_xml.strip().encode()).iter(f"{BPMN_NS}scriptTask"):
		name = task.get(SERVER_SCRIPT_ATTR)
		connected = task.find(f"{BPMN_NS}incoming") is not None or task.find(f"{BPMN_NS}outgoing") is not None
		if connected or not name or not frappe.db.exists("Server Script", name):
			continue
		if not frappe.has_permission("Server Script", "read", doc=name):
			continue
		functions = function_signatures(frappe.db.get_value("Server Script", name, "script") or "")
		if functions is not None:
			libraries.append({"name": name, "functions": functions})
	return libraries


def function_signatures(code: str) -> list[str] | None:
	"""Each function code defines as name(args); None when code does more than define functions."""
	try:
		body = ast.parse(code).body
	except SyntaxError:
		return []
	if any(not isinstance(node, ast.FunctionDef) for node in body):
		return None
	return [f"{node.name}({ast.unparse(node.args)})" for node in body]


def library_text(libraries: list[dict]) -> str:
	"""The library section of the text Logix reads."""
	lines = [
		"LIBRARY SCRIPTS ON THIS MAP: reuse these functions instead of writing them again. "
		'Load one with lib = import_script("<library name>") and call lib.<function>(...).'
	]
	for library in libraries:
		lines.append(
			f"- {library['name']}: {', '.join(library['functions']) or 'no functions could be read'}"
		)
	return "\n".join(lines)
