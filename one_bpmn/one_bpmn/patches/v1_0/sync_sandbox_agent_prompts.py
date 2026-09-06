"""
Bring the three sandbox agents' configurations up to what their maps now run.

A Processa export carries a map and its Server Scripts but not the AI Agent
Configuration, so a site that imported the new Frontend, Dev and Mobile maps
still ran them against prompts that called retired tools, and the Mobile App
Agent still based on ``staging`` — a branch its sandbox clone does not have.
The prompts come from the seed patches, the single source of truth for them.
"""

import frappe

_AGENT_SEEDS = {
	"Frontend Agent": "one_bpmn.one_bpmn.patches.v1_0.seed_frontend_agent_config",
	"Dev Agent": "one_bpmn.one_bpmn.patches.v1_0.seed_dev_agent_config",
	"Mobile App Agent": "one_bpmn.one_bpmn.patches.v1_0.seed_mobile_app_agent_config",
}
_MOBILE_BASE_BRANCH = "version-15"


def execute():
	for agent, module in _AGENT_SEEDS.items():
		if not frappe.db.exists("AI Agent Configuration", agent):
			continue
		doc = frappe.get_doc("AI Agent Configuration", agent)
		doc.system_prompt = frappe.get_attr(module + "._SYSTEM_PROMPT")
		if agent == "Mobile App Agent":
			_set_constant(doc, "base_branch", _MOBILE_BASE_BRANCH)
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)


def _set_constant(doc, name: str, value: str) -> None:
	for row in doc.constants or []:
		if (row.constant_name or "").strip() == name:
			row.constant_value = value
			return
	doc.append("constants", {"constant_name": name, "constant_value": value})
