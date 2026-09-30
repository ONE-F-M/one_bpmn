"""LuCrusher's phase 4 to 6 skills require a source on everything they list.

Each skill gains a Sources section, and its finalize line names the source or references
key that finalize now requires. A skill already carrying the section is left as a person
edited it.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL, TASKS_SKILL, TOPOLOGY_SKILL

MARKER = "## Sources"

NO_SOURCE_RULE = (
	"A process, step, lane or field that has no source in the fetched Lucidchart document or the "
	"codebase scan is not listed. Never add one from general knowledge of how such a process "
	"usually works."
)

EDITS = {
	TOPOLOGY_SKILL: {
		"replace": (
			"processes:[{process_name, type, reason, shapes}]",
			"processes:[{process_name, type, reason, shapes, source}]",
		),
		"section": (
			f"{MARKER}\n"
			"Every process names its source: the Lucidchart page title its shapes are on. "
			f"{NO_SOURCE_RULE} finalize rejects a process without a source.\n"
		),
	},
	TASKS_SKILL: {
		"section": (
			f"{MARKER}\n"
			"Every task lists its references: the Lucidchart page titles and the code file paths "
			f"from the codebase scan it comes from. {NO_SOURCE_RULE} finalize rejects a task "
			"without references.\n"
		),
	},
	PROSALLY_SKILL: {
		"replace": ("prompt_block}]}", "prompt_block, source}]}"),
		"section": (
			f"{MARKER}\n"
			"Every prompt block names its source: the Lucidchart page title the process is drawn on. "
			f"{NO_SOURCE_RULE} finalize rejects a prompt block without a source.\n"
		),
	},
}


def execute():
	for skill_name, edit in EDITS.items():
		doc = frappe.get_doc("AI Skill", {"skill_name": skill_name})
		body = doc.body
		if MARKER in body:
			continue
		if "replace" in edit:
			body = body.replace(*edit["replace"])
		body = body.rstrip("\n")
		doc.body = f"{body}\n\n{edit['section']}"
		doc.save(ignore_permissions=True)
