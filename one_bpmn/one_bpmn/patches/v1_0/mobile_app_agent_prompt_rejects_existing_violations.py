"""The Mobile App Agent learns not to treat an existing violation as the answer.

Its Adversarial suite's live runs caught the same shape twice: a hardcoded
staging host and a route missing requiresAuth were both already present in the
sandbox, and the agent pointed at the existing file as satisfying the work
order instead of refusing it. The configuration's prompt is the one that
reaches the model, and it is the record no export carries, so it is the
record this patch touches.

The rule is appended as a block whose first line is the marker: a hand-edited
prompt keeps its edits above the block, and a reworded rule replaces the
block instead of stacking a second one.
"""

import frappe

RULES = """\
An existing violation of these rules is not the answer:
- If a file already breaks one of these rules - a hardcoded host, a route missing requiresAuth that needs it, a token outside secure storage, or any other rule above - finding it does not satisfy a work order asking for the same thing again. Say what you found and that it is against the rules, and stop rather than pointing to it as the answer.
"""

AGENT = "Mobile App Agent"


def marker(rules: str) -> str:
	return rules.strip().splitlines()[0]


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT):
		return
	doc = frappe.get_doc("AI Agent Configuration", AGENT)
	head = (doc.system_prompt or "").split(marker(RULES))[0].rstrip()
	prompt = head + "\n\n" + RULES.strip() + "\n"
	if prompt == doc.system_prompt:
		return
	doc.system_prompt = prompt
	doc.save(ignore_permissions=True)
