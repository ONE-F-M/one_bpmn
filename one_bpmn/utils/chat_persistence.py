"""
Chat persistence helpers for Logix and ProsAlly.

Stores conversation history in the shared Chat Conversation / Chat Message
DocTypes (owned by onefm_mcp).  Each conversation is tagged with an
``agent_mode`` ("Logix" or "ProsAlly") so that queries by one agent never
surface chats from the other — or from Lumina.

Ephemeral session state (not conversation history) stays in Redis for speed.
"""

import json

import frappe


# ── Conversation management ────────────────────────────────────────────────────

def create_conversation(agent_mode: str, title: str, user: str) -> str:
	"""Create a new Chat Conversation document and return its name.

	Mirrors the pattern used by Lumina's ``create_conversation()`` but
	sets ``agent_mode`` to "Logix" or "ProsAlly" for proper isolation.
	"""
	doc = frappe.get_doc({
		"doctype": "Chat Conversation",
		"title": title[:140],
		"agent_mode": agent_mode,
		"status": "Open",
		"participants": [{"user": user}],
		"last_updated": frappe.utils.now_datetime(),
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def close_conversation(conversation_name: str) -> None:
	"""Mark a Chat Conversation as Closed."""
	if frappe.db.exists("Chat Conversation", conversation_name):
		frappe.db.set_value("Chat Conversation", conversation_name, {
			"status": "Closed",
			"last_updated": frappe.utils.now_datetime(),
		})
		frappe.db.commit()


# ── Message persistence ────────────────────────────────────────────────────────

def _agent_name(conversation_name: str) -> str:
	"""Return the agent display name for a conversation (e.g. 'Logix', 'ProsAlly')."""
	agent_mode = frappe.db.get_value("Chat Conversation", conversation_name, "agent_mode")
	return agent_mode or "Logix"


def save_user_message(conversation_name: str, text: str) -> str:
	"""Persist a user message and update conversation metadata."""
	return _save_message(
		conversation_name=conversation_name,
		message_type="User",
		text=text,
		sender=frappe.session.user,
		receiver=_agent_name(conversation_name),
	)


def save_bot_message(conversation_name: str, text: str, metadata: dict | None = None) -> str:
	"""Persist an agent (bot) message and update conversation metadata."""
	return _save_message(
		conversation_name=conversation_name,
		message_type="Bot",
		text=text,
		sender=_agent_name(conversation_name),
		receiver="User",
		metadata=metadata,
	)


def _save_message(
	conversation_name: str,
	message_type: str,
	text: str,
	sender: str,
	receiver: str,
	metadata: dict | None = None,
) -> str:
	"""Insert a Chat Message document and update the parent conversation."""
	if not conversation_name or not frappe.db.exists("Chat Conversation", conversation_name):
		frappe.throw("Invalid conversation")

	if frappe.db.get_value("Chat Conversation", conversation_name, "owner") != frappe.session.user:
		frappe.throw("Not permitted", frappe.PermissionError)

	msg_doc = frappe.get_doc({
		"doctype": "Chat Message",
		"conversation": conversation_name,
		"sender": sender,
		"receiver": receiver,
		"message_type": message_type,
		"text": text,
		"metadata": json.dumps(metadata, default=str) if metadata else None,
	})
	msg_doc.insert(ignore_permissions=True)

	# Update conversation metadata (last_message pointer + timestamp)
	frappe.db.set_value("Chat Conversation", conversation_name, {
		"last_message": msg_doc.name,
		"last_updated": frappe.utils.now_datetime(),
	})
	frappe.db.commit()

	return msg_doc.name


# ── History loading ────────────────────────────────────────────────────────────

def load_history(conversation_name: str, limit: int = 30) -> list[dict]:
	"""
	Return the last *limit* User/Bot messages as a list of
	{"role": "user"|"assistant", "content": "..."} dicts, oldest first.

	Reads from the Chat Message table (same DocType Lumina uses).
	"""
	if not conversation_name or not frappe.db.exists("Chat Conversation", conversation_name):
		return []

	messages = frappe.db.get_all(
		"Chat Message",
		fields=["message_type", "text"],
		filters={
			"conversation": conversation_name,
			"message_type": ["in", ["User", "Bot"]],
		},
		order_by="creation desc",
		limit=limit,
	)

	# Reverse so oldest is first (chronological order)
	messages.reverse()

	return [
		{
			"role": "user" if m["message_type"] == "User" else "assistant",
			"content": m["text"] or "",
		}
		for m in messages
	]


# ── Conversation state (stays in Redis — ephemeral per-session) ────────────────

def get_or_create_state(conversation_name: str, initial_data: dict | None = None) -> dict:
	"""
	Return the Chat Conversation State for *conversation_name*, creating one if
	it doesn't exist yet.  Returns the parsed state_data as a dict.

	NOTE: State is ephemeral per-session data (e.g. the current step in a
	multi-step agent flow).  It is intentionally kept in Redis for speed.
	"""
	state_dict = frappe.cache.get_value(f"chat_state:{conversation_name}")
	if state_dict:
		return state_dict.get("state_data") or {}

	data = initial_data or {}
	new_state = {
		"conversation": conversation_name,
		"state_data": data,
		"iteration": 0,
		"last_checkpoint": frappe.utils.now_datetime().isoformat(),
	}
	frappe.cache.set_value(f"chat_state:{conversation_name}", new_state)
	return data


def update_state(conversation_name: str, data: dict) -> None:
	"""Overwrite the state_data for a conversation's Chat Conversation State."""
	state_dict = frappe.cache.get_value(f"chat_state:{conversation_name}")
	if not state_dict:
		state_dict = {
			"conversation": conversation_name,
			"iteration": 0,
		}
	state_dict["state_data"] = data
	state_dict["last_checkpoint"] = frappe.utils.now_datetime().isoformat()
	frappe.cache.set_value(f"chat_state:{conversation_name}", state_dict)
