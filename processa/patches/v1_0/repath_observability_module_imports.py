import frappe
from frappe.utils import cint

from processa.ai_agent_security.code_checks.script_gate import script_hash

# Old dotted path to new, for the observability modules and the Insights API that moved.
MOVED_MODULES = {
	"processa.agents.observability": "processa.ai_agent_observability.observability",
	"processa.agents.pricing": "processa.ai_agent_observability.pricing",
	"processa.agents.goal_completion": "processa.ai_agent_observability.goal_completion",
	"processa.api.insights_api": "processa.api.insights",
}


def execute():
	"""Point Server Script imports at the moved observability and Insights modules and keep each approval valid."""
	for old in MOVED_MODULES:
		for name in frappe.get_all("Server Script", filters={"script": ["like", f"%{old}%"]}, pluck="name"):
			_repath_script(name)
	frappe.clear_cache(doctype="Server Script")


def _repath_script(name: str) -> None:
	row = frappe.db.get_value(
		"Server Script", name, ["script", "processa_approved", "processa_approved_hash"], as_dict=True
	)
	script = row.script
	for old, new in MOVED_MODULES.items():
		script = script.replace(old, new)
	if script == row.script:
		return
	values = {"script": script}
	if cint(row.processa_approved) and row.processa_approved_hash == script_hash(row.script):
		values["processa_approved_hash"] = script_hash(script)
	frappe.db.set_value("Server Script", name, values, update_modified=False)
