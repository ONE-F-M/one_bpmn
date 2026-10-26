"""Docu's display-condition case ends its expected trace at the field-property stage.

The stage writes the reply and marks the turn done, so no finalize follows it. Only that one case is
refreshed, and a second run changes nothing.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_baseline_cases as seed
from one_bpmn.one_bpmn.patches.v1_0.docu_baseline_matches_the_current_agent import REFRESHED_CASES

DISPLAY_CASE = REFRESHED_CASES[1]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": seed.AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "suite_type": "Baseline"}, "name"
	)
	if not suite or not frappe.db.exists("AI Eval Case", {"suite": suite, "title": DISPLAY_CASE}):
		return
	spec = next(c for c in seed.CASES if c["title"] == DISPLAY_CASE)
	seed.upsert_case(suite, process_model, spec)
