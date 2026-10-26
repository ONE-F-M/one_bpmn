"""ProsAlly stage scripts that name their skills in the line itself read them from the stage constant instead.

A site that ran prosally_stage_skills before it moved to constants keeps the hard-coded line; this swaps
it for the constants line and adds the two constants. Idempotent: a script without the old line is left.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_stage_skills import (
	AGENT_ID,
	STAGE_CONSTANTS,
	STAGES,
	_set_stage_constants,
	skill_line,
)

HARD_CODED_LINE = (
	r'_system = "\n\n".join([_system] + ["## Skill: " + _sk.name + "\n\n" + _sk.body for _sk in '
	r'frappe.get_all("AI Skill", filters={"name": ["in", ["bpmn-modelling-rules-and-ir-schema", '
	r'"prosally-node-types-and-flow-rules"]], "status": "Active"}, fields=["name", "body"], '
	r'order_by="name asc")])'
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	_set_stage_constants(name)
	for sub_agent_id, script_pattern in STAGES.items():
		script_name = frappe.db.get_value("Server Script", {"name": ["like", script_pattern]}, "name")
		if not script_name:
			continue
		doc = frappe.get_doc("Server Script", script_name)
		if HARD_CODED_LINE not in doc.script:
			continue
		doc.script = doc.script.replace(HARD_CODED_LINE, skill_line(STAGE_CONSTANTS[sub_agent_id]), 1)
		doc.save(ignore_permissions=True)
