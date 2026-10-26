"""The agents that edit code are told to delete a file they no longer need, not to empty it."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

AGENTS = ("Dev Agent", "Frontend Agent", "Mobile App Agent", "Bug Programmer")

RULES = """\
Removing files:
- To remove a file that is no longer needed, call delete_file. Never empty it with write_file.
- Say in your report which files you deleted and why.
"""


def marker() -> str:
	return RULES.splitlines()[0]


def execute():
	for name in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", name):
			continue
		doc = frappe.get_doc("AI Agent Configuration", name)
		prompt = with_block(doc.system_prompt, RULES)
		if prompt != doc.system_prompt:
			doc.system_prompt = prompt
			doc.save(ignore_permissions=True)
