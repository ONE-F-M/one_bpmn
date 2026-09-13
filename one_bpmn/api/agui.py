# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The shared AG-UI chat endpoint (WI-001670).

Every chat message — for any agent — goes through this one door and the
reply streams back as standard AG-UI events over Server-Sent Events. The
frontend consumes it with EventSource (GET), exactly as the Lumina page
consumes its stream today; returning a werkzeug Response from a whitelisted
method is the same production-proven pattern as lumina.stream_message.

Agent resolution, permission checks (allowed_roles), PII screening and
runner selection all live in invoke_agent — this module only owns transport.
"""

import frappe
from frappe import _
from werkzeug.wrappers import Response

from one_bpmn.agents.agui_stream import agent_event_stream


@frappe.whitelist()
def stream_agent_turn(
	agent_id: str, message: str, conversation: str = None, context: str = None
):
	"""Stream one agent turn as AG-UI events (SSE).

	Args:
	    agent_id: AI Agent Configuration.agent_id to run.
	    message: the user's input for this turn.
	    conversation: existing Chat Conversation to continue; created from
	        the agent's configuration when omitted (WI-001619 path).
	    context: optional JSON dict merged into the turn payload
	        (editor state, dialog grounding, etc.).

	Returns:
	    text/event-stream response: RunStarted → content events →
	    RunFinished (RunError before the terminal event on failure).
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	parsed_context = frappe.parse_json(context) if context else {}

	if not conversation:
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		conversation = create_agent_conversation(
			agent_id, title=(message or _("New chat"))[:140], user=frappe.session.user
		)
		# EventSource turns are separate GET requests; commit so the next
		# turn (and any parallel reader) sees the conversation immediately.
		frappe.db.commit()

	return Response(
		agent_event_stream(agent_id, message, conversation, parsed_context),
		mimetype="text/event-stream",
		headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
	)


@frappe.whitelist()
def conversation_history(conversation: str, limit: int = 30, before: str = None) -> list:
	"""Prior turns for the shared panel's resume-or-create lifecycle
	(WI-001672). load_history already enforces owner-only access — an
	unknown or foreign conversation reads as empty, never as an error.

	Each assistant turn carries the ``events`` it produced while streaming, so a
	reopened conversation shows the cards and option buttons it showed the first
	time. They are rebuilt here by replaying the same translators the live
	stream uses over the stored result — one definition of what a reply renders
	as, rather than a second one in the browser that drifts from it.

	``before`` pages backwards: pass the oldest message already on screen and
	the previous page comes back. A page shorter than ``limit`` is the end.
	"""
	from frappe.utils import cint

	from one_bpmn.utils.chat_persistence import load_history

	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	messages = load_history(conversation, limit=min(cint(limit) or 30, 100), before=before)
	for message in messages:
		metadata = message.pop("metadata", None) or {}
		message["events"] = _replayed_events(metadata) if message["role"] == "assistant" else []
	return messages


def _replayed_events(metadata: dict) -> list:
	"""The custom events a stored turn would emit again, as {name, value}.

	The result the turn produced is kept under ``agent_result`` — the same place
	the live runner reads it back from. Anything else stored there is not a
	reply and is ignored.
	"""
	result = metadata.get("agent_result")
	if not isinstance(result, dict):
		return []

	from one_bpmn.agents.agui_stream import _extension_events

	events = []
	for event in _extension_events(result):
		name = getattr(event, "name", "")
		if not name:
			continue
		events.append({"name": name, "value": getattr(event, "value", None) or {}})
	return events


@frappe.whitelist()
def list_conversations(limit: int = 30) -> list:
	"""The current user's chat conversations for the one-ai history sidebar
	(WI-001678), newest first. Owner-scoped by construction.

	Restricted to the page's own agents. A chat belonging to another surface
	— Logix, ProsAlly, Docu, anything registered later — is not browsable
	here: the page cannot resume it, and the legacy Lumina sidebar excluded
	exactly the same conversations (_registry_only_agent_modes in lumina.py,
	written after 154 Docu chats leaked into it).
	"""
	from frappe.utils import cint

	from one_bpmn.api.agent_invocation import one_ai_conversation_modes

	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))
	return frappe.get_all(
		"Chat Conversation",
		filters={"owner": frappe.session.user, "agent_mode": ["in", one_ai_conversation_modes()]},
		fields=["name", "title", "agent_mode", "last_updated", "status"],
		order_by="last_updated desc",
		limit=min(cint(limit) or 30, 100),
	)
