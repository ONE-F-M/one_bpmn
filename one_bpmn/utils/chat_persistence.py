"""
Chat persistence helpers for Logix and ProsAlly.

Wraps Chat Conversation / Chat Message / Chat Conversation State so that
agent pipelines can persist history and state without knowing Frappe ORM details.
"""

import frappe


# ── Conversation management ────────────────────────────────────────────────────

def create_conversation(agent_mode: str, title: str, user: str) -> str:
    """Create a new Chat Conversation and return its name."""
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
    frappe.db.set_value("Chat Conversation", conversation_name, {
        "status": "Closed",
        "last_updated": frappe.utils.now_datetime(),
    })
    frappe.db.commit()


# ── Message persistence ────────────────────────────────────────────────────────

def _agent_name(conversation_name: str) -> str:
    """Return the agent display name for a conversation (e.g. 'Logix', 'ProsAlly')."""
    mode = frappe.db.get_value("Chat Conversation", conversation_name, "agent_mode") or "Lumina"
    return mode


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
    msg = frappe.get_doc({
        "doctype": "Chat Message",
        "conversation": conversation_name,
        "sender": sender,
        "receiver": receiver,
        "message_type": message_type,
        "text": text,
        "metadata": frappe.as_json(metadata) if metadata else None,
    })
    msg.insert(ignore_permissions=True)

    frappe.db.set_value("Chat Conversation", conversation_name, {
        "last_message": msg.name,
        "last_updated": frappe.utils.now_datetime(),
    })
    frappe.db.commit()
    return msg.name


# ── History loading ────────────────────────────────────────────────────────────

def load_history(conversation_name: str, limit: int = 30) -> list[dict]:
    """
    Return the last *limit* User/Bot messages as a list of
    {"role": "user"|"assistant", "content": "..."} dicts, oldest first.
    """
    rows = frappe.db.get_all(
        "Chat Message",
        filters={
            "conversation": conversation_name,
            "message_type": ["in", ["User", "Bot"]],
        },
        fields=["message_type", "text"],
        order_by="creation asc",
        limit=limit,
    )
    return [
        {
            "role": "user" if r.message_type == "User" else "assistant",
            "content": r.text or "",
        }
        for r in rows
    ]


# ── Conversation state ─────────────────────────────────────────────────────────

def get_or_create_state(conversation_name: str, initial_data: dict | None = None) -> dict:
    """
    Return the Chat Conversation State for *conversation_name*, creating one if
    it doesn't exist yet.  Returns the parsed state_data as a dict.
    """
    existing = frappe.db.get_value(
        "Chat Conversation State",
        {"conversation": conversation_name},
        ["name", "state_data"],
        as_dict=True,
    )
    if existing:
        try:
            import json
            return json.loads(existing.state_data or "{}")
        except Exception:
            return {}

    state = frappe.get_doc({
        "doctype": "Chat Conversation State",
        "conversation": conversation_name,
        "agent_mode": frappe.db.get_value("Chat Conversation", conversation_name, "agent_mode"),
        "state_data": frappe.as_json(initial_data or {}),
        "iteration": 0,
        "last_checkpoint": frappe.utils.now_datetime(),
    })
    state.insert(ignore_permissions=True)
    frappe.db.commit()
    return initial_data or {}


def update_state(conversation_name: str, data: dict) -> None:
    """Overwrite the state_data for a conversation's Chat Conversation State."""
    state_name = frappe.db.get_value(
        "Chat Conversation State", {"conversation": conversation_name}, "name"
    )
    if not state_name:
        get_or_create_state(conversation_name, data)
        return

    frappe.db.set_value("Chat Conversation State", state_name, {
        "state_data": frappe.as_json(data),
        "last_checkpoint": frappe.utils.now_datetime(),
    })
    frappe.db.commit()
