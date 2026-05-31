"""
Chat persistence helpers for Logix and ProsAlly.

Wraps Chat Conversation / Chat Message / Chat Conversation State so that
agent pipelines can persist history and state without writing to the database.
All chat details are stored in Redis cache for maximum speed and absolute privacy.
"""

import frappe


# ── Conversation management ────────────────────────────────────────────────────

def create_conversation(agent_mode: str, title: str, user: str) -> str:
    """Create a new Chat Conversation and return its name."""
    conv_name = f"CONV-{frappe.generate_hash(length=12)}"
    conv_dict = {
        "name": conv_name,
        "title": title[:140],
        "agent_mode": agent_mode,
        "status": "Open",
        "participants": [{"user": user}],
        "last_updated": frappe.utils.now_datetime().isoformat(),
        "messages": [],
    }
    frappe.cache.set_value(f"chat_conv:{conv_name}", conv_dict)
    return conv_name


def close_conversation(conversation_name: str) -> None:
    conv_dict = frappe.cache.get_value(f"chat_conv:{conversation_name}")
    if conv_dict:
        conv_dict["status"] = "Closed"
        conv_dict["last_updated"] = frappe.utils.now_datetime().isoformat()
        frappe.cache.set_value(f"chat_conv:{conversation_name}", conv_dict)


# ── Message persistence ────────────────────────────────────────────────────────

def _agent_name(conversation_name: str) -> str:
    """Return the agent display name for a conversation (e.g. 'Logix', 'ProsAlly')."""
    conv_dict = frappe.cache.get_value(f"chat_conv:{conversation_name}")
    if conv_dict:
        return conv_dict.get("agent_mode") or "Lumina"
    return "Lumina"


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
    msg_name = f"MSG-{frappe.generate_hash(length=12)}"
    msg = {
        "name": msg_name,
        "conversation": conversation_name,
        "sender": sender,
        "receiver": receiver,
        "message_type": message_type,
        "text": text,
        "metadata": metadata,
        "creation": frappe.utils.now_datetime().isoformat(),
    }

    conv_dict = frappe.cache.get_value(f"chat_conv:{conversation_name}")
    if not conv_dict:
        # Auto-initialize fallback
        conv_dict = {
            "name": conversation_name,
            "title": "Restored Chat",
            "agent_mode": "ProsAlly" if "ProsAlly" in sender or "ProsAlly" in receiver else "Logix",
            "status": "Open",
            "participants": [{"user": frappe.session.user}],
            "last_updated": frappe.utils.now_datetime().isoformat(),
            "messages": [],
        }

    conv_dict["messages"].append(msg)
    conv_dict["last_message"] = msg_name
    conv_dict["last_updated"] = frappe.utils.now_datetime().isoformat()
    frappe.cache.set_value(f"chat_conv:{conversation_name}", conv_dict)
    return msg_name


# ── History loading ────────────────────────────────────────────────────────────

def load_history(conversation_name: str, limit: int = 30) -> list[dict]:
    """
    Return the last *limit* User/Bot messages as a list of
    {"role": "user"|"assistant", "content": "..."} dicts, oldest first.
    """
    conv_dict = frappe.cache.get_value(f"chat_conv:{conversation_name}")
    if not conv_dict or not conv_dict.get("messages"):
        return []

    # Filter and slice
    filtered = [
        msg for msg in conv_dict["messages"]
        if msg.get("message_type") in ["User", "Bot"]
    ]
    sliced = filtered[-limit:]
    
    return [
        {
            "role": "user" if r["message_type"] == "User" else "assistant",
            "content": r["text"] or "",
        }
        for r in sliced
    ]


# ── Conversation state ─────────────────────────────────────────────────────────

def get_or_create_state(conversation_name: str, initial_data: dict | None = None) -> dict:
    """
    Return the Chat Conversation State for *conversation_name*, creating one if
    it doesn't exist yet.  Returns the parsed state_data as a dict.
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
