"""Move LuCrusher's per-conversation state out of hidden Tool messages into session state.

Save Response records the snapshot in session state; this carries each
conversation's latest hidden note across so a resumed migration keeps its place.
"""

import json

import frappe

from one_bpmn.agents.memory.session_state import set_state

STATE_SENTINEL = "__lucrusher_state__"


def execute():
	rows = frappe.get_all(
		"Chat Message",
		filters={"message_type": "Tool", "text": STATE_SENTINEL},
		fields=["name", "conversation", "metadata", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	latest = {}
	for row in rows:
		latest[row.conversation] = row
	for conversation, row in latest.items():
		snapshot = _snapshot(row.name, row.metadata)
		if snapshot:
			set_state(conversation, snapshot, commit=False)
	frappe.db.delete("Chat Message", {"message_type": "Tool", "text": STATE_SENTINEL})


def _snapshot(message: str, raw) -> dict:
	try:
		blob = json.loads(raw) if raw else None
	except ValueError:
		frappe.log_error(title=f"LuCrusher state note {message} is not JSON; dropped", message=str(raw)[:2000])
		return {}
	if not isinstance(blob, dict):
		return {}
	inner = blob.get(STATE_SENTINEL)
	return inner if isinstance(inner, dict) else blob
