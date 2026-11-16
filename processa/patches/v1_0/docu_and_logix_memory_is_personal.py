"""Docu and Logix recall each person's own memories plus the shared ones, and the Logix sub-agents keep none."""

import frappe

PERSONAL = ("docu_agent", "logix_agent")
NO_MEMORY = ("logix_intent_classifier", "logix_clarifier", "logix_script_writer", "logix_tool_writer")


def execute():
	for agent_id in PERSONAL:
		for name in frappe.get_all("AI Agent Configuration", filters={"agent_id": agent_id}, pluck="name"):
			frappe.db.set_value("AI Agent Configuration", name, "memory_scope", "User and Agent")
	for agent_id in NO_MEMORY:
		for name in frappe.get_all("AI Agent Configuration", filters={"agent_id": agent_id}, pluck="name"):
			frappe.db.set_value("AI Agent Configuration", name, "long_term_memory", "Disabled")
