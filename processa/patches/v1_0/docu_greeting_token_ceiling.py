"""Docu's greeting ceiling is set above what the agent's own turn costs, about 1,800 tokens.

A designed DocType costs 7,000 or more, so 2,500 still catches a greeting that starts designing.
"""

import frappe

AGENT_ID = "docu_agent"
OLD_CEILING = "500"
NEW_CEILING = "2500"


def execute():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "suite_type": "Baseline"}, "name"
	)
	if not suite:
		return
	cases = frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name")
	if not cases:
		return
	for name in frappe.get_all(
		"AI Eval Assertion",
		filters={
			"parenttype": "AI Eval Case",
			"parent": ["in", cases],
			"assertion_type": "max_tokens",
			"value": OLD_CEILING,
		},
		pluck="name",
	):
		frappe.db.set_value("AI Eval Assertion", name, "value", NEW_CEILING)
