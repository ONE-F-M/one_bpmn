"""The Bug Programmer is told to batch its edits, and the Bug Planner and Reviewer to read and search with fewer calls."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

READING = """\
Reading efficiently:
- Read the files you need in one read_files call, and read each file once.
- To find where several names are used, make one grep_files call with a|b|c in the pattern instead of one call per name.
- Do not repeat a search with different wording. Read the most likely file instead.
"""

RULES = {
	"Bug Programmer": """\
Batching edits:
- Before your first edit, list every change you already know you need, in this file and in others, and make them in one apply_edits call (up to 20 replacements, one commit). Use edit_file only when exactly one change is left.
- Two edit_file calls in a row means you should have used apply_edits.
""",
	"Bug Planner": READING,
	"Bug Reviewer": READING,
}


def marker(agent: str) -> str:
	return RULES[agent].splitlines()[0]


def execute():
	for agent, rules in RULES.items():
		if not frappe.db.exists("AI Agent Configuration", agent):
			continue
		doc = frappe.get_doc("AI Agent Configuration", agent)
		prompt = with_block(doc.system_prompt, rules)
		if prompt != doc.system_prompt:
			doc.system_prompt = prompt
			doc.save(ignore_permissions=True)
