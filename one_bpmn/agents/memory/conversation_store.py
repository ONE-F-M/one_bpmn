"""
Short-term (per-agent) conversation store for BPMN AI agents.

Each AI Agent Task / Subprocess owns ONE conversation thread, keyed by
(instance_name, bpmn_id), so one agent's history never leaks into another
agent's context. A message is a plain dict with the same shape the executor
history slot uses:

    {"role": str, "content": str, "tool_calls"?: list, "tool_call_id"?: str}

Three backends behind a single interface (see ``get_conversation_store``):

- "process_variable" (default): the thread lives in the live spiff task's
  ``task.data["{bpmn_id}_conversation"]`` and dies with the instance — today's
  behaviour, no new storage. The live task is injected via the factory.
- "document_store": the thread is persisted so it survives the instance,
  reusing onefm_mcp's Chat Conversation / Chat Message doctypes.
- "custom": resolves a ConversationStore subclass from the ``ai_conversation_store``
  hook so an app can supply its own store.

A ContextWindowPolicy (max_messages, retain_system_prompt) lives in this layer
so callers stay within model limits.

MIGRATION NOTE (known limitation):
    onefm_mcp's Chat Conversation / Chat Message are reused cross-app for now by
    explicit decision. They are to be MOVED into one_bpmn later (same approach as
    the AI Model Pricing move) and generalised with a BPMN-appropriate role
    vocabulary — the onefm_mcp Chat Message.message_type / receiver / agent_mode
    Selects have no BPMN-specific values, so the canonical role and the BPMN
    context (instance_name, bpmn_id) are carried in Chat Message.metadata and
    Chat Conversation.title. ALL onefm_mcp coupling is confined to
    ``DocumentConversationStore`` so the move touches one class.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass

import frappe
from frappe import _

# Roles that make up a multi-turn thread (same vocabulary as the executor).
MESSAGE_ROLES = ("system", "user", "assistant", "tool")

# Reserved agent_mode for an AI Agent Task's own persisted memory thread. It must
# never equal any agent's chat_mode_label: Chat Conversation.agent_mode defaults to
# "General Chat", so an unset value made every memory thread look like a user
# opening General Chat, and that map's After-Insert trigger then spawned a phantom
# instance which waited for messages forever and never closed.
AGENT_MEMORY_MODE = "one_bpmn:agent-memory"


def conversation_data_key(bpmn_id: str) -> str:
	"""Deterministic ``task.data`` key for a BPMN element's thread."""
	return f"{bpmn_id}_conversation"


def _clean_message(message: dict) -> dict:
	"""Validate and reduce a message to the canonical shape, dropping absent
	optional keys so load()/append() round-trip identically."""
	if not isinstance(message, dict):
		frappe.throw(_("A conversation message must be a dict."))
	role = message.get("role")
	if not role:
		frappe.throw(_("A conversation message requires a 'role'."))
	out = {"role": role, "content": message.get("content", "")}
	if message.get("tool_calls") is not None:
		out["tool_calls"] = message.get("tool_calls")
	if message.get("tool_call_id") is not None:
		out["tool_call_id"] = message.get("tool_call_id")
	return out


def _json_loads(value):
	if not value:
		return None
	try:
		return json.loads(value)
	except (ValueError, TypeError):
		return None


# ── Context-window policy ──────────────────────────────────────────────────
@dataclass
class ContextWindowPolicy:
	"""Trims a thread to fit the model context window.

	When a thread is longer than ``max_messages``, keep the system message (if
	present and ``retain_system_prompt``) plus the most recent
	``max_messages - 1`` messages, so the system prompt is always retained.
	"""

	max_messages: int
	retain_system_prompt: bool = True

	def apply(self, messages: list[dict]) -> list[dict]:
		messages = list(messages or [])
		if not self.max_messages or len(messages) <= self.max_messages:
			return messages

		system = None
		rest = messages
		if self.retain_system_prompt:
			for i, m in enumerate(messages):
				if (m or {}).get("role") == "system":
					system = m
					rest = messages[:i] + messages[i + 1:]
					break

		if system is not None:
			keep = self.max_messages - 1
			tail = rest[-keep:] if keep > 0 else []
			return [system] + tail
		return messages[-self.max_messages:]


# ── Interface ───────────────────────────────────────────────────────────────
class ConversationStore(abc.ABC):
	"""Single interface every backend implements.

	Subclasses implement ``_load_raw`` and ``append``; ``load`` wraps
	``_load_raw`` and applies the context-window policy uniformly.
	"""

	def __init__(self, policy: ContextWindowPolicy | None = None):
		self.policy = policy

	@abc.abstractmethod
	def _load_raw(self, instance_name: str, bpmn_id: str) -> list[dict]:
		"""Return the full ordered thread for (instance_name, bpmn_id)."""
		raise NotImplementedError

	@abc.abstractmethod
	def append(self, instance_name: str, bpmn_id: str, message: dict) -> None:
		"""Append a single message to the (instance_name, bpmn_id) thread."""
		raise NotImplementedError

	def load(self, instance_name: str, bpmn_id: str) -> list[dict]:
		messages = self._load_raw(instance_name, bpmn_id) or []
		if self.policy is not None:
			messages = self.policy.apply(messages)
		return messages


# ── process_variable (default) ───────────────────────────────────────────────
class ProcessVariableStore(ConversationStore):
	"""Stores the thread in the live spiff task's ``task.data`` under
	``{bpmn_id}_conversation``. Lost when the instance is deleted — today's
	behaviour, no new storage.

	The live task is required (there is no ``task.data`` without it) and is
	injected via ``get_conversation_store("process_variable", task=task)``.
	``instance_name`` is part of the interface for uniformity; the task is
	already scoped to a single instance, so the bpmn_id key alone separates
	threads within it.
	"""

	def __init__(self, task=None, policy: ContextWindowPolicy | None = None):
		super().__init__(policy=policy)
		self.task = task

	def _task_data(self) -> dict:
		task = self.task
		if task is None or not isinstance(getattr(task, "data", None), dict):
			frappe.throw(
				_(
					"The 'process_variable' conversation store requires a live workflow "
					"task. Pass it via get_conversation_store('process_variable', task=task)."
				)
			)
		return task.data

	def _load_raw(self, instance_name: str, bpmn_id: str) -> list[dict]:
		thread = self._task_data().get(conversation_data_key(bpmn_id))
		return list(thread) if isinstance(thread, list) else []

	def append(self, instance_name: str, bpmn_id: str, message: dict) -> None:
		data = self._task_data()
		key = conversation_data_key(bpmn_id)
		thread = data.get(key)
		if not isinstance(thread, list):
			thread = []
		thread.append(_clean_message(message))
		data[key] = thread


# ── document_store (persistent, via onefm_mcp) ───────────────────────────────
class DocumentConversationStore(ConversationStore):
	"""Persists the thread using onefm_mcp's Chat Conversation / Chat Message.

	This class is the ONLY place that references the onefm_mcp doctypes (see the
	module migration note). Mapping:
	    role         -> Chat Message.message_type  (best-effort; canonical role in metadata)
	    content      -> Chat Message.text
	    tool_calls   -> Chat Message.tool_calls (JSON)
	    tool_call_id -> Chat Message.tool_call_id
	The BPMN context + canonical role live in Chat Message.metadata, and the
	(instance_name, bpmn_id) key is encoded in Chat Conversation.title.
	"""

	_CONVERSATION_DOCTYPE = "Chat Conversation"
	_MESSAGE_DOCTYPE = "Chat Message"
	# role -> message_type (Select options are only User/Bot/Tool)
	_ROLE_TO_MESSAGE_TYPE = {"user": "User", "assistant": "Bot", "system": "Bot", "tool": "Tool"}
	# reverse fallback when a message has no canonical role in metadata
	_MESSAGE_TYPE_TO_ROLE = {"User": "user", "Bot": "assistant", "Tool": "tool"}

	def _title(self, instance_name: str, bpmn_id: str) -> str:
		return f"one_bpmn:{instance_name}:{bpmn_id}"

	def _get_conversation(self, instance_name: str, bpmn_id: str, create: bool = False):
		title = self._title(instance_name, bpmn_id)
		name = frappe.db.get_value(self._CONVERSATION_DOCTYPE, {"title": title}, "name")
		if name or not create:
			return name
		conv = frappe.get_doc(
			{
				"doctype": self._CONVERSATION_DOCTYPE,
				"title": title,
				"status": "Open",
				# A memory thread is NOT a user chat, and it must not be mistaken
				# for one. Chat Conversation.agent_mode defaults to "General Chat",
				# so leaving it unset made every persisted agent thread look exactly
				# like somebody opening General Chat — and once General Chat had a
				# process map, its After-Insert trigger fired on each one and spawned
				# a phantom instance that waited for messages forever and never
				# closed. This sentinel matches no agent's chat_mode_label, so no
				# start trigger can ever match it.
				"agent_mode": AGENT_MEMORY_MODE,
			}
		)
		conv.insert(ignore_permissions=True)
		return conv.name

	def _load_raw(self, instance_name: str, bpmn_id: str) -> list[dict]:
		conv = self._get_conversation(instance_name, bpmn_id)
		if not conv:
			return []
		rows = frappe.get_all(
			self._MESSAGE_DOCTYPE,
			filters={"conversation": conv},
			fields=["text", "message_type", "tool_calls", "tool_call_id", "metadata", "creation"],
			order_by="creation asc",
		)
		# Order by the explicit seq in metadata first (robust against equal
		# creation timestamps), falling back to creation order.
		parsed = []
		for r in rows:
			meta = _json_loads(r.get("metadata")) or {}
			parsed.append((meta.get("seq", 0), r.get("creation"), self._row_to_message(r, meta)))
		parsed.sort(key=lambda t: (t[0], t[1]))
		return [p[2] for p in parsed]

	def append(self, instance_name: str, bpmn_id: str, message: dict) -> None:
		message = _clean_message(message)
		conv = self._get_conversation(instance_name, bpmn_id, create=True)
		role = message["role"]
		seq = frappe.db.count(self._MESSAGE_DOCTYPE, {"conversation": conv})
		meta = {"bpmn_instance": instance_name, "bpmn_id": bpmn_id, "role": role, "seq": seq}
		tool_calls = message.get("tool_calls")
		frappe.get_doc(
			{
				"doctype": self._MESSAGE_DOCTYPE,
				"conversation": conv,
				"message_type": self._ROLE_TO_MESSAGE_TYPE.get(role, "Bot"),
				"text": message.get("content", ""),
				"tool_calls": json.dumps(tool_calls) if tool_calls is not None else None,
				"tool_call_id": message.get("tool_call_id"),
				"metadata": json.dumps(meta),
			}
		).insert(ignore_permissions=True)

	def _row_to_message(self, row: dict, meta: dict) -> dict:
		role = meta.get("role") or self._MESSAGE_TYPE_TO_ROLE.get(row.get("message_type"), "assistant")
		msg = {"role": role, "content": row.get("text") or ""}
		tool_calls = _json_loads(row.get("tool_calls"))
		if tool_calls is not None:
			msg["tool_calls"] = tool_calls
		if row.get("tool_call_id"):
			msg["tool_call_id"] = row.get("tool_call_id")
		return msg


# ── custom (app-supplied) ────────────────────────────────────────────────────
def _resolve_custom_store_class():
	hooks = frappe.get_hooks("ai_conversation_store")
	target = hooks[-1] if isinstance(hooks, (list, tuple)) and hooks else hooks
	if not target:
		frappe.throw(
			_(
				"No custom conversation store is registered. Set the "
				"'ai_conversation_store' hook in hooks.py to a ConversationStore subclass."
			)
		)
	return frappe.get_attr(target)


# ── Factory ──────────────────────────────────────────────────────────────────
def get_conversation_store(
	backend: str,
	*,
	task=None,
	policy: ContextWindowPolicy | None = None,
) -> ConversationStore:
	"""Return the conversation store for the given backend.

	Args:
	    backend: "process_variable" | "document_store" | "custom"
	    task: the live spiff task (required for "process_variable").
	    policy: optional ContextWindowPolicy applied on load().
	"""
	backend = backend or "process_variable"

	if backend == "process_variable":
		return ProcessVariableStore(task=task, policy=policy)
	if backend == "document_store":
		return DocumentConversationStore(policy=policy)
	if backend == "custom":
		store_cls = _resolve_custom_store_class()
		return store_cls(policy=policy)

	frappe.throw(_("Unknown conversation store backend: {0}").format(backend))
