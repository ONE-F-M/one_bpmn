"""A stage tool that failed is reported to the user as a failure, not answered with a request for more detail.

ProsAlly's finalize writes a TOOL_ERROR reply when no stage answered and the turn store holds a
tool_error, and ProsAlly and LuCrusher Save Response carry tool_error into the Bot message metadata.
Scripts are found by api_method. Idempotent: each edit applies only once.
"""

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import _edit_script

FINALIZE_ANCHOR = 'else:\n    output = {\n        "intent": "CLARIFY",'
FINALIZE_BLOCK = (
	'elif turn.get("tool_error"):\n'
	"    output = {\n"
	'        "intent": "TOOL_ERROR",\n'
	'        "action_intent": None,\n'
	'        "response": "I could not draw the diagram because a tool failed. The team has been notified.",\n'
	'        "options": [],\n'
	"    }\n"
	"    update_turn(context_docname, output=output, done=True)\n"
	'    result["finalized"] = True\n'
	'    result["tool_error"] = True\n'
)
CARRY_TOOL_ERROR = (
	'if isinstance(_turn, dict) and _turn.get("tool_error"):\n    _meta["tool_error"] = _turn["tool_error"]'
)

PROSALLY_META_ANCHOR = '_meta = {"intent": intent}'
LUCRUSHER_META_ANCHOR = (
	'msg.metadata = json.dumps({"intent": intent, "agent_result": agent_result}, default=str)'
)
LUCRUSHER_META = (
	'_meta = {"intent": intent, "agent_result": agent_result}\n'
	f"{CARRY_TOOL_ERROR}\n"
	"msg.metadata = json.dumps(_meta, default=str)"
)


def execute():
	_edit_script("prosally_tool_finalize", FINALIZE_ANCHOR, FINALIZE_BLOCK + FINALIZE_ANCHOR)
	_edit_script(
		"prosally_save_response", PROSALLY_META_ANCHOR, f"{PROSALLY_META_ANCHOR}\n{CARRY_TOOL_ERROR}"
	)
	_edit_script("lucrusher_save_response", LUCRUSHER_META_ANCHOR, LUCRUSHER_META)
