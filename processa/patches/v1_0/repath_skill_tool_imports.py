import frappe
from frappe.utils import cint

from processa.ai_agent_security.code_checks.script_gate import script_hash

# Old dotted path to new, for the skill and tool modules that moved into ai_agent_skills.
MOVED_MODULES = {
	"processa.agents.shape_tools": "processa.ai_agent_skills.tools.shape_tools",
	"processa.agents.tool_pool": "processa.ai_agent_skills.tools.tool_pool",
	"processa.api.skill_tools": "processa.ai_agent_skills.skill_tools",
	"processa.api.skills_api": "processa.api.skills",
	"processa.api.skill_creator": "processa.api.skills",
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
