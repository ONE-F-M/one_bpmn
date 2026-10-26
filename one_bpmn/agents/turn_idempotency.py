# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One reply per message, however many times the client sends it.

A dropped connection, an impatient retry or a double submit all deliver the same
message twice. Without a key to recognise it by, the second delivery is just
another message: another agent run, another bill, another reply to a question
that was only asked once.

The client mints an id and sends it with the turn. The user's Chat Message
carries it, and the reply's name is recorded on that row, so a redelivery is
answered from what is already saved.

The user message is written HERE rather than left to the map, and the map is
handed its name through ``context["message_name"]`` — every agent's "Save User
Message" task already reuses a message passed that way instead of inserting its
own, so the id reaches the transcript without touching a single Server Script.
"""

from __future__ import annotations

import json

import frappe

# Where the reply's name is kept on the user's own message row. In the existing
# metadata JSON rather than a second Link field: nothing else needs to query it,
# and one field for "what this message produced" is enough.
_REPLY_KEY = "reply_message"


def find_existing(conversation: str, client_message_id: str) -> dict | None:
	"""The reply already produced for this id, or None if this is the first time.

	Returns None when the id is known but its turn never produced a reply — the
	turn crashed, or is still running. Re-running is the right answer there: a
	message with no answer is worse than a repeated one.
	"""
	if not (conversation and client_message_id):
		return None

	name = frappe.db.get_value(
		"Chat Message",
		{
			"conversation": conversation,
			"client_message_id": client_message_id,
			"message_type": "User",
		},
		"name",
	)
	if not name:
		return None

	reply = _reply_of(name)
	if not reply:
		return None

	row = frappe.db.get_value("Chat Message", reply, ["text", "metadata"], as_dict=True)
	if not row:
		return None

	result = {"response": row.text or "", "conversation": conversation, "replayed": True}
	agent_result = (_loads(row.metadata) or {}).get("agent_result")
	if isinstance(agent_result, dict):
		result.update({k: v for k, v in agent_result.items() if k not in result})
	return result


def record_user_message(
	conversation: str, message: str, client_message_id: str, existing: str = ""
) -> str:
	"""Persist the user's message with its id and return its name.

	The caller passes that name to the map so it is reused rather than inserted
	a second time. When the caller already wrote the row — the Lumina page does,
	before it streams — the id is stamped onto it instead, or the transcript ends
	up with the same message twice.
	"""
	if existing and frappe.db.exists("Chat Message", existing):
		frappe.db.set_value(
			"Chat Message", existing, "client_message_id", client_message_id,
			update_modified=False,
		)
		return existing

	doc = frappe.new_doc("Chat Message")
	doc.conversation = conversation
	doc.sender = frappe.session.user
	doc.text = message
	doc.message_type = "User"
	doc.client_message_id = client_message_id
	doc.insert(ignore_permissions=True)
	return doc.name


def record_reply(user_message: str, reply_message: str) -> None:
	"""Note which reply answered this message, so a redelivery can return it."""
	if not (user_message and reply_message):
		return
	try:
		meta = _loads(frappe.db.get_value("Chat Message", user_message, "metadata")) or {}
		meta[_REPLY_KEY] = reply_message
		frappe.db.set_value(
			"Chat Message", user_message, "metadata", json.dumps(meta), update_modified=False
		)
	except Exception:
		# A turn that answered correctly must not fail because its receipt did.
		frappe.log_error(
			title="Chat reply not recorded against its message",
			message=frappe.get_traceback(),
		)


def _reply_of(user_message: str) -> str:
	meta = _loads(frappe.db.get_value("Chat Message", user_message, "metadata")) or {}
	reply = meta.get(_REPLY_KEY)
	return reply if reply and frappe.db.exists("Chat Message", reply) else ""


def _loads(raw):
	if not raw:
		return {}
	try:
		return json.loads(raw)
	except Exception:
		return {}
