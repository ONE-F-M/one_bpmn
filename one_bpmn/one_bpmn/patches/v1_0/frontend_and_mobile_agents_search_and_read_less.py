"""The Frontend and Mobile App agents are told how to search and read with fewer calls."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

RULES = {
	"Frontend Agent": """\
Searching and reading efficiently (front end):
- search_frontend takes one literal string and costs a call each time. Ask it one question at a time, and no more than three times for the same question.
- To look for several names at once, use grep_files on the sandbox with a|b|c in one pattern.
- Start from locate_ui. Read the files it names, with one sibling, in a single read_files call before you search again.
- Read each file once. Its text stays in front of you, so do not read it again.
- For two or more replacements, in one file or several, use one apply_edits call instead of one edit_file call each.
""",
	"Mobile App Agent": """\
Searching and reading efficiently (mobile app):
- search_repo goes through GitHub code search and often answers nothing. After one empty answer, use grep_files on the sandbox with a|b|c in one pattern.
- Read the files you will change, with one sibling, in a single read_files call, and read each file once.
- For two or more replacements, in one file or several, use one apply_edits call instead of one edit_file call each.
""",
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
