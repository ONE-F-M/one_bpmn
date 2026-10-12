"""The agents that edit code are told how to spend their turns, and to wrap up when the budget line says so."""

import frappe

AGENTS = ("Dev Agent", "Frontend Agent", "Mobile App Agent", "Bug Programmer")

RULES = """\
Working within your turns:
- After each tool result you see a run budget line. Treat it as the real limit on this run.
- Search once per question. Join the words you are after in one grep_files pattern instead of one call per word.
- Never run more than three searches in a row without reading a file or making an edit.
- If a search finds nothing useful, do not reword the same pattern. Read the most likely file with read_files.
- Make your first edit before a third of your turns are gone. An edit you can test is worth more than another search.
- After each edit, run the test that covers it with run_tests before you search again.
- When the budget line tells you to wrap up, run the tests, open the pull request with what you have, and say in your report what is unfinished.
"""


def marker() -> str:
	return RULES.splitlines()[0]


def execute():
	for name in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", name):
			continue
		doc = frappe.get_doc("AI Agent Configuration", name)
		# The block is the tail of the prompt, so a reworded rule replaces it instead of stacking.
		head = (doc.system_prompt or "").split(marker())[0].rstrip()
		prompt = head + "\n\n" + RULES.strip() + "\n"
		if prompt != doc.system_prompt:
			doc.system_prompt = prompt
			doc.save(ignore_permissions=True)
