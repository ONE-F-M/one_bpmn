import frappe
from frappe.utils import now_datetime

from processa.ai_agent_security.code_checks.script_gate import approved_names, script_hash
from processa.ai_agent_security.code_checks.script_validator import inspect_script

PROCESSA_BACKEND = "Processa backend"


def processa_imports(code: str) -> frozenset:
	"""The Processa backend names code uses."""
	return frozenset(f["name"] for f in inspect_script(code) if f["category"] == PROCESSA_BACKEND)


def execute():
	"""Approve each Server Script whose only findings are Processa backend names, for those names."""
	for script in frappe.get_all(
		"Server Script",
		fields=["name", "script", "processa_approved", "processa_approved_hash", "processa_allowed_modules"],
	):
		names = processa_imports(script.script)
		allowed = approved_names(script) | names
		if not names or inspect_script(script.script, allowed):
			continue
		frappe.db.set_value(
			"Server Script",
			script.name,
			{
				"processa_allowed_modules": "\n".join(sorted(allowed)),
				"processa_approved": 1,
				"processa_approved_by": "Administrator",
				"processa_approved_on": now_datetime(),
				"processa_approved_hash": script_hash(script.script),
			},
		)
