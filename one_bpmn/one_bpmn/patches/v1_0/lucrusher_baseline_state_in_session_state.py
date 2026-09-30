"""LuCrusher Baseline cases seed the migration state where Build Context reads it.

Build Context reads session state, so a case that carries the state in a hidden
__lucrusher_state__ Tool message ran with no document, topology or tasks. Each such
message is merged into the case's session_state and dropped from its messages.
"""

import json

import frappe

from one_bpmn.agents.eval_runner import SEED_MESSAGES_KEY, SEED_STATE_KEY
from one_bpmn.one_bpmn.patches.v1_0.move_lucrusher_state_to_session_state import STATE_SENTINEL
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import SUITE_TITLE


def execute():
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite:
		return
	for case in frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["name", "input_context"]):
		context = json.loads(case.input_context or "{}")
		messages = context.get(SEED_MESSAGES_KEY) or []
		notes = [m for m in messages if m.get("text") == STATE_SENTINEL]
		if not notes:
			continue
		state = dict(context.get(SEED_STATE_KEY) or {})
		for note in notes:
			state.update({k: v for k, v in (note.get("metadata") or {}).items() if v is not None})
		context[SEED_MESSAGES_KEY] = [m for m in messages if m.get("text") != STATE_SENTINEL]
		context[SEED_STATE_KEY] = state
		frappe.db.set_value("AI Eval Case", case.name, "input_context", json.dumps(context, indent=1))
