"""Logix and its sub-agents get bounded context, enough output room and timeouts, and a guard rail that agrees with the modifying skill."""

import frappe

SETTINGS = {
	"logix_agent": {"context_max_messages": 20, "temperature": 0},
	"logix_script_writer": {"max_tokens": 8192},
	"logix_tool_writer": {"max_tokens": 8192},
	"logix_test_writer": {"max_tokens": 2048, "timeout_seconds": 60, "max_retries": 2},
	"logix_script_reviewer": {"timeout_seconds": 60, "max_retries": 2},
}
GUARDRAIL_AGENT = "logix_agent"
GUARDRAIL_CATEGORY = "Cost & Tokens"
GUARDRAIL = "Keep explanations short; when returning code, return the full script."


def execute():
	for agent_id, values in SETTINGS.items():
		for name in frappe.get_all("AI Agent Configuration", filters={"agent_id": agent_id}, pluck="name"):
			doc = frappe.get_doc("AI Agent Configuration", name)
			doc.update(values)
			if agent_id == GUARDRAIL_AGENT:
				for row in doc.guardrails:
					if row.category == GUARDRAIL_CATEGORY:
						row.guardrail = GUARDRAIL
			doc.save(ignore_permissions=True)
