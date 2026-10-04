"""Mark the chat conversations that eval runs created, so the chat history sidebar leaves them out.

An eval conversation drives a BPMN Process Instance whose AI Agent Runs have origin eval.
"""

import frappe


def execute():
	instances = frappe.get_all(
		"AI Agent Run",
		filters={"origin": "eval", "instance": ["is", "set"]},
		pluck="instance",
		distinct=True,
	)
	if not instances:
		return
	conversations = frappe.get_all(
		"BPMN Process Instance",
		filters={"name": ["in", instances], "context_doctype": "Chat Conversation"},
		pluck="context_docname",
	)
	marked = 0
	for name in set(conversations):
		if name and frappe.db.get_value("Chat Conversation", name, "is_eval") == 0:
			frappe.db.set_value("Chat Conversation", name, "is_eval", 1, update_modified=False)
			marked += 1
	print(f"Marked {marked} eval chat conversation(s)")
