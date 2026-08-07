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
