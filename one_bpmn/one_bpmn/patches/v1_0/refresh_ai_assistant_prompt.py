"""
WI-001624: refresh the AI Assistant configuration's system prompt from the
updated builder so the clarify-when-unsure guidance takes effect on the
already-seeded agent. Idempotent — safe to re-run.
"""

import frappe


def execute():
	if not frappe.db.exists("AI Agent Configuration", {"agent_id": "ai_agent_assistant"}):
		return
	try:
		from one_bpmn.api.ai_assistant import _build_system_prompt

		prompt = _build_system_prompt()
	except Exception:
		return

	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": "ai_agent_assistant"}, "name")
	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt, update_modified=False)
	frappe.cache.delete_value("agent_config:ai_agent_assistant")
	frappe.db.commit()
