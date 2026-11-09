import frappe
from frappe.utils import cint

from one_bpmn.ai_agent_security.code_checks.script_gate import script_hash

# Old dotted path to new, for the skill and tool modules that moved into ai_agent_skills.
MOVED_MODULES = {
	"one_bpmn.agents.shape_tools": "one_bpmn.ai_agent_skills.tools.shape_tools",
	"one_bpmn.agents.tool_pool": "one_bpmn.ai_agent_skills.tools.tool_pool",
	"one_bpmn.api.skill_tools": "one_bpmn.ai_agent_skills.skill_tools",
	"one_bpmn.api.skills_api": "one_bpmn.api.skills",
	"one_bpmn.api.skill_creator": "one_bpmn.api.skills",
}


def execute():
	"""Point Server Script imports at the moved skill and tool modules and keep each approval valid."""
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
