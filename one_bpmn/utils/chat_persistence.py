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


def create_agent_conversation(agent_id: str, title: str = None, user: str = None) -> str:
	"""Create a Chat Conversation for an agent purely from its configuration
	(WI-001619).

	Reads the chat mode label off the agent's AI Agent Configuration and
	stamps it on the conversation, so callers never hardcode a mode string.
	Newly-created agents use this directly; the existing per-agent endpoints
	(ProsAlly / Logix / Docu / Lumina) are repointed to it in their own
	migration stories.
	"""
	from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

	config = get_agent_config(agent_id)
	if not config:
		frappe.throw(frappe._("No enabled AI Agent Configuration for agent '{0}'.").format(agent_id))

	return create_conversation(
		agent_mode=config.get("chat_mode_label") or agent_id,
		title=title or frappe._("New chat"),
		user=user or frappe.session.user,
	)


def close_conversation(conversation_name: str) -> None:
	"""End a chat conversation by handing control to its process map.

	This delivers ``ChatConversation_Close_Action`` to the BPMN Process Instance
	driving the conversation; the diagram's close branch (Cleanup → Conversation
	Ended) is what actually marks the conversation Closed and finalises it.

	Orphaned conversations — no live instance, e.g. inserted while no map with
	the matching start trigger was active, or the instance later Errored — are
	closed directly instead: with no map to run the close branch they would
	otherwise stay Open forever, and a panel that resumes the newest Open
	conversation re-enters them every time (observed live 2026-08-09, after a
	map retirement window left ProsAlly conversations instance-less).
	"""
	if not frappe.db.exists("Chat Conversation", conversation_name):
		return

	inst_name = frappe.db.get_value(
		"BPMN Process Instance",
		{
			"context_doctype": "Chat Conversation",
			"context_docname": conversation_name,
			"status": "Active",
		},
		"name",
	)
	from one_bpmn.api.skill_tools import clear_conversation_skills

	if not inst_name:
		# No orchestration is running — close the conversation record itself so
		# it can't be resumed into the same dead end.
		frappe.db.set_value("Chat Conversation", conversation_name, "status", "Closed")
		clear_conversation_skills(conversation_name)
		return

	try:
		instance = frappe.get_doc("BPMN Process Instance", inst_name)
		instance.receive_message("ChatConversation_Close_Action", payload={})
		clear_conversation_skills(conversation_name)
	except frappe.ValidationError:
		pass  # instance not waiting for the close message — nothing to do
	except Exception:
		frappe.log_error(title="BPMN close delivery failed", message=frappe.get_traceback())


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

def load_history(conversation_name: str, limit: int = 30, before: str = None) -> list[dict]:
	"""
	Return the last *limit* User/Bot messages as a list of
	{"role": "user"|"assistant", "content": "...", "message": "<row name>",
	"timestamp": "...", "metadata": {...}} dicts, oldest first.

	``before`` is a Chat Message name: only messages older than it are returned,
	which is how a reopened conversation pages back past the limit instead of
	being stuck with whatever fitted in the first read.

	``metadata`` is what the turn stored beside its text — the structured result
	that became cards and option buttons while the reply was streaming. Returned
	so a reopened conversation can show those again rather than the words alone.

	``message`` is the Chat Message name (WI-001822). A resumed conversation
	otherwise redraws its replies with no identity, so a rating the user left
	before reloading could not be shown back to them — and they would rate the
	same reply twice, seeing an empty control each time.

	``timestamp`` is the row's ``creation`` datetime as a string (site timezone,
	WI-002047).

	Reads from the Chat Message table (same DocType Lumina uses).
	"""
	if not conversation_name or not frappe.db.exists("Chat Conversation", conversation_name):
		return []

	if frappe.db.get_value("Chat Conversation", conversation_name, "owner") != frappe.session.user:
		return []

	filters = {
		"conversation": conversation_name,
		"message_type": ["in", ["User", "Bot"]],
	}
	if before:
		# Paged by creation, not by name: names are hashes and carry no order. A
		# cursor that has gone reads as no cursor rather than an error — the
		# caller gets the newest page again instead of a failure.
		cutoff = frappe.db.get_value("Chat Message", before, "creation")
		if cutoff:
			filters["creation"] = ["<", cutoff]

	messages = frappe.db.get_all(
		"Chat Message",
		fields=["name", "message_type", "text", "creation", "metadata"],
		filters=filters,
		order_by="creation desc",
		limit=limit,
	)

	# Reverse so oldest is first (chronological order)
	messages.reverse()

	return [
		{
			"role": "user" if m["message_type"] == "User" else "assistant",
			"content": m["text"] or "",
			"message": m["name"],
			"timestamp": str(m["creation"]) if m["creation"] else None,
			"metadata": _parsed_metadata(m.get("metadata")),
		}
		for m in messages
	]


def _parsed_metadata(raw) -> dict:
	"""Stored metadata as a dict. Unreadable metadata is no metadata: a turn
	that saved something malformed must still show its text."""
	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		parsed = json.loads(raw)
	except Exception:
		return {}
	return parsed if isinstance(parsed, dict) else {}


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
