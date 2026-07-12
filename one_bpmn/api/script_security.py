"""
Whitelisted API for live script-security feedback in the Logix editor.

Thin HTTP wrapper around the structural validator so the frontend can lint a
Server Script as it is typed — the same checks the pre-deployment gate enforces,
so what the author sees live is exactly what will block a save/deploy.
"""

import frappe

from one_bpmn.security.script_validator import deep_inspect_script


@frappe.whitelist()
def lint_server_script(code: str = "") -> dict:
	"""
	Structurally lint a script and return its security violations.

	Args:
		code: the Python source shown in the editor.

	Returns:
		{"valid": bool, "violations": [message, ...]}  (violations empty when clean)
	"""
	violations = deep_inspect_script(code or "")
	return {"valid": len(violations) == 0, "violations": violations}
