# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One reply per message, however many times the client sends it."""

from __future__ import annotations

import json

import frappe

_REPLY_KEY = "reply_message"


def find_existing(conversation: str, client_message_id: str) -> dict | None:
	"""The reply already produced for this id, or None if this is the first time."""
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


def record_user_message(conversation: str, message: str, client_message_id: str, existing: str = "") -> str:
	"""Persist the user's message with its id and return its name.
	A row the caller already wrote gets the id stamped on it, so the transcript holds the message once."""
	if existing and frappe.db.exists("Chat Message", existing):
		frappe.db.set_value(
			"Chat Message",
			existing,
			"client_message_id",
			client_message_id,
			update_modified=False,
		)
		return existing

	doc = frappe.new_doc("Chat Message")
	doc.conversation = conversation
	doc.sender = frappe.session.user
	doc.text = message
	doc.message_type = "User"
	doc.client_message_id = client_message_id
	doc.insert(ignore_permissions=True)  # the sender's own message in a conversation the endpoint resolved
	return doc.name


def record_reply(user_message: str, reply_message: str) -> None:
	"""Note which reply answered this message, so a redelivery can return it."""
	if not (user_message and reply_message):
		return
	try:
		meta = _loads(frappe.db.get_value("Chat Message", user_message, "metadata")) or {}
		meta[_REPLY_KEY] = reply_message
		frappe.db.set_value("Chat Message", user_message, "metadata", json.dumps(meta), update_modified=False)
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
