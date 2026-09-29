"""ProsAlly Baseline cases stop expecting finalize, which never runs after a stage tool writes the reply."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_prosally_baseline_suite import SUITE_TITLE


def execute():
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite:
		return
	cases = frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name")
	if not cases:
		return
	frappe.db.delete(
		"AI Eval Expected Tool Call",
		{"parenttype": "AI Eval Case", "parent": ["in", cases], "tool_name": "finalize"},
	)
