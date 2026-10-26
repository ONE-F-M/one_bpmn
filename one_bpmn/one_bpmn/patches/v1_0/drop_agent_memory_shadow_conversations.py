"""Delete the shadow conversations the conversation store wrote and nothing read.

The history step reads the person's own conversation, so the per-instance
copies the store kept are noise.
"""

import frappe
from frappe.utils import create_batch

from one_bpmn.agents.memory.conversation_store import AGENT_MEMORY_MODE


def execute():
	names = frappe.get_all("Chat Conversation", filters={"agent_mode": AGENT_MEMORY_MODE}, pluck="name")
	for batch in create_batch(names, 200):
		frappe.db.delete("Chat Message", {"conversation": ["in", batch]})
		frappe.db.delete("Chat Participant", {"parent": ["in", batch], "parenttype": "Chat Conversation"})
		frappe.db.delete("Chat Conversation", {"name": ["in", batch]})
