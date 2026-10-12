"""Docu Baseline's clarify cases stop expecting finalize, which does nothing once clarify has written the reply."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_docu_baseline_cases import AGENT_ID


def execute():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "suite_type": "Baseline"}, "name"
	)
	if not suite:
		return
	cases = frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name")
	clarify_cases = frappe.get_all(
		"AI Eval Expected Tool Call",
		filters={"parenttype": "AI Eval Case", "parent": ["in", cases or [""]], "tool_name": "clarify"},
		pluck="parent",
	)
	if not clarify_cases:
		return
	frappe.db.delete(
		"AI Eval Expected Tool Call",
		{"parenttype": "AI Eval Case", "parent": ["in", clarify_cases], "tool_name": "finalize"},
	)
