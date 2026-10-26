"""The Frontend adversarial case about revealing the system prompt is scored by its judge alone.

Its work order can carry a legitimate part the agent rightly works on, so the no-edits assertion is
dropped from that one case. A second run changes nothing.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_frontend_agent_adversarial_suite import CASES, SUITE_TITLE

CASE_TITLE = CASES[0]["title"]


def execute():
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	name = suite and frappe.db.get_value("AI Eval Case", {"suite": suite, "title": CASE_TITLE}, "name")
	if not name:
		return

	case = frappe.get_doc("AI Eval Case", name)
	kept = [row for row in case.assertions if row.assertion_type != "no_tool_call"]
	if len(kept) == len(case.assertions):
		return

	case.set("assertions", kept)
	case.save(ignore_permissions=True)
