"""Conversations the frontend saved as Administrator get their real owner back.

With if_owner deciding who may read a conversation, a row whose owner is
Administrator belongs to nobody who can see it. Where the person is still on the
record — the participant row the frontend wrote, or the first message they sent —
the owner is set to them. A row with no such trace was Administrator's own and is
left alone.

User messages whose owner differs from their sender are aligned the same way,
because write access to a message is checked against its owner.
"""

import frappe


def _person_for(conversation: str) -> str | None:
	participant = frappe.db.get_value(
		"Chat Participant",
		{"parent": conversation, "parenttype": "Chat Conversation", "user": ["not in", ["Administrator", ""]]},
		"user",
		order_by="idx asc",
	)
	if participant:
		return participant
	return frappe.db.get_value(
		"Chat Message",
		{"conversation": conversation, "message_type": "User", "sender": ["not in", ["Administrator", ""]]},
		"sender",
		order_by="creation asc",
	)


def execute():
	repaired = 0
	for name in frappe.get_all("Chat Conversation", filters={"owner": "Administrator"}, pluck="name"):
		person = _person_for(name)
		if person and frappe.db.exists("User", person):
			frappe.db.set_value("Chat Conversation", name, "owner", person, update_modified=False)
			repaired += 1

	frappe.db.sql(
		"""
		UPDATE `tabChat Message` m
		INNER JOIN `tabUser` u ON u.name = m.sender
		SET m.owner = m.sender
		WHERE m.message_type = 'User' AND m.owner <> m.sender
		"""
	)
	frappe.clear_cache(doctype="Chat Conversation")
	frappe.clear_cache(doctype="Chat Message")
	if repaired:
		frappe.logger("one_bpmn").info(f"chat_conversation_owner_is_the_person: {repaired} conversations handed back")
