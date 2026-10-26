"""Logix answers a question about the linked script in words, and its clarifier always offers options.

The writer's modify skill and its OUTPUT section both asked for the full script, which outweighed the
question rule beneath them. The clarifier's "whenever possible" let it return an empty option list.
Each edit is anchored and applied once; the Logix Baseline cases are reseeded with them.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_baseline_suite

SKILL = "modifying-an-existing-script"
SKILL_ANCHOR = "# Changing an existing script\n"
SKILL_RULE = (
	"First: if the person only asks about the script (what it does, why it failed) and asks for no "
	"change, do not rewrite it. Answer in two or three plain sentences, write no code block, and stop.\n"
)

PROMPT_EDITS = {
	"logix_script_writer": (
		"OUTPUT:\n",
		"OUTPUT (when the person asked for a change; a question gets the QUESTIONS answer below instead):\n",
	),
	"logix_clarifier": (
		"options to choose from whenever possible",
		"options to choose from, every time, never an empty list",
	),
}


def execute():
	body = frappe.db.get_value("AI Skill", SKILL, "body")
	if body and SKILL_RULE not in body and SKILL_ANCHOR in body:
		body = body.replace(SKILL_ANCHOR, SKILL_ANCHOR + "\n" + SKILL_RULE, 1)
		frappe.db.set_value("AI Skill", SKILL, "body", body)

	for agent_id, (old, new) in PROMPT_EDITS.items():
		name, prompt = frappe.db.get_value(
			"AI Agent Configuration", {"agent_id": agent_id}, ["name", "system_prompt"]
		) or (None, None)
		if name and new not in (prompt or "") and old in (prompt or ""):
			frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.replace(old, new, 1))

	seed_logix_baseline_suite.execute()
