"""Point the LuCrusher Baseline judge checks at a model that is enabled on this site.

The first seed named claude-sonnet-4-5-20250929, which is disabled on some sites, so every
llm_judge check failed with "AI Model ... is disabled". Checks whose judge model is missing
or disabled move to the agent's own model, or another enabled model of its provider.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import AGENT_ID, SUITE_TITLE, judge_for


def execute():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not agent or not suite:
		return
	judge_provider, judge_model = judge_for(agent)
	if not judge_model:
		return

	enabled = set(frappe.get_all("AI Model", filters={"enable_model": 1}, pluck="name"))
	for case_name in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
		case = frappe.get_doc("AI Eval Case", case_name)
		stale = [
			a for a in case.assertions if a.assertion_type == "llm_judge" and a.judge_model not in enabled
		]
		for a in stale:
			a.judge_provider = judge_provider
			a.judge_model = judge_model
		if stale:
			case.save(ignore_permissions=True)
			print(f"{case.title}: {len(stale)} judge check(s) now use {judge_model}")
