"""ProsAlly's orchestrator keeps no enabled skills.

Any enabled row gives it load_skill, unload_skill and load_skill_resource on every turn, and its
prompt allows exactly three calls. The generate and modify stages read their skills by name.
"""

import frappe

AGENT_ID = "prosally_agent"


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	frappe.db.delete("AI Agent Enabled Skill", {"parenttype": "AI Agent Configuration", "parent": name})
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
