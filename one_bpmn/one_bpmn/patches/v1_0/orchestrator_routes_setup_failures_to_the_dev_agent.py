"""The Orchestrator is told which defects go to the Bug Agent and which to the Dev Agent."""

import frappe

AGENT = "Orchestrator Agent"

RULES = """\
Choosing between the Bug Agent and the Dev Agent:
- Send a defect to the Bug Agent only when a test in the repository can reproduce it: existing code that gives a wrong result for a known input.
- Send failures of installing, migrating, patches, fixtures, test records or app setup to the Dev Agent. No unit test reproduces them, so the Bug Agent cannot start.
- If the brief gives no way to tell, choose the Dev Agent.
"""


def marker() -> str:
	return RULES.splitlines()[0]


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT):
		return
	doc = frappe.get_doc("AI Agent Configuration", AGENT)
	# The block is the tail of the prompt, so a reworded rule replaces it instead of stacking.
	head = (doc.system_prompt or "").split(marker())[0].rstrip()
	prompt = head + "\n\n" + RULES.strip() + "\n"
	if prompt != doc.system_prompt:
		doc.system_prompt = prompt
		doc.save(ignore_permissions=True)
