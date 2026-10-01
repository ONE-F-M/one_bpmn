"""LuCrusher Baseline drafting cases check that the phase skill reached the prompt, not that load_skill ran.

Build Context loads the phase skill before the turn, so on these cases the model calls finalize first
and load_skill not at all. Cases already carrying a skill_in_prompt assertion are left as they are.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import SUITE_TITLE
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL, TASKS_SKILL, TOPOLOGY_SKILL

DRAFTING_CASES = {
	"Analysing the topology loads the topology skill": TOPOLOGY_SKILL,
	"Generating migration tasks loads the migration task skill": TASKS_SKILL,
	"Writing ProsAlly prompts loads the ProsAlly skill": PROSALLY_SKILL,
}


def execute():
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite:
		return
	for title, skill in DRAFTING_CASES.items():
		name = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
		if not name:
			continue
		case = frappe.get_doc("AI Eval Case", name)
		if any(a.assertion_type == "skill_in_prompt" for a in case.assertions):
			continue
		calls = [row for row in case.expected_tool_calls if row.tool_name != "load_skill"]
		renumber = {order: i + 1 for i, order in enumerate(sorted({row.call_order for row in calls}))}
		for row in calls:
			row.call_order = renumber[row.call_order]
		case.set("expected_tool_calls", calls)
		case.append("assertions", {"assertion_type": "skill_in_prompt", "value": skill})
		case.append("assertions", {"assertion_type": "no_tool_call", "value": "load_skill"})
		case.save(ignore_permissions=True)
