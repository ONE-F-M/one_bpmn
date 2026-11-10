import frappe
from frappe.utils import cint

from one_bpmn.ai_agent_security.code_checks.script_gate import script_hash

# Old dotted path to new, for the observability modules and the Insights API that moved.
MOVED_MODULES = {
	"one_bpmn.agents.observability": "one_bpmn.ai_agent_observability.observability",
	"one_bpmn.agents.pricing": "one_bpmn.ai_agent_observability.pricing",
	"one_bpmn.agents.goal_completion": "one_bpmn.ai_agent_observability.goal_completion",
	"one_bpmn.api.insights_api": "one_bpmn.api.insights",
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
