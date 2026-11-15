"""The replies ProsAlly's routed stages write: a clarifying question, a redirect, and the turn that lost its reply."""

import frappe
from frappe import _

from processa.ai_agent_registry.definitions.prosally.helpers import complete_sub_prompt, prosally_config
from processa.ai_agent_registry.definitions.prosally.tools_prompts import dms_answer_output
from processa.ai_agent_registry.definitions.shared.helpers import extract_json, format_history
from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn

NO_STAGE_REPLY = "NO_STAGE_REPLY"


def clarify_output(conversation: str) -> dict:
	"""Ask one question that names the missing piece, from the clarifier or from the classification reason."""
	turn = get_turn(conversation)
	parts = []
	if turn.get("process_name"):
		parts.append("Process: " + turn["process_name"])
	reason = turn.get("intent_reason") or ""
	parts.append("Classification reason: " + reason)
	history = format_history(turn.get("chat_history"))
	if history:
		parts.append("Conversation so far:\n" + history)
	parts.append("User message: " + (turn.get("user_text") or ""))
	data = extract_json(complete_sub_prompt(prosally_config(), "clarifier", "\n\n".join(parts))) or {}
	question = data.get("question") or missing_piece_question(reason)
	options = data.get("options") or []
	output = {"intent": "CLARIFY", "action_intent": None, "response": question, "options": options}
	update_turn(conversation, output=output, done=True)
	return {"response": question, "options": options}


def missing_piece_question(reason: str) -> str:
	"""The question for the first missing piece the classification reason names, else the three pieces at once."""
	words = (reason or "").lower()
	starts = _("What starts this process, a person raising a request or something the system does?")
	questions = (
		("lane", _("Which teams or roles take part, so I can draw one lane for each?")),
		("trigger", starts),
		("start", starts),
		("end", _("What does it look like when this process is finished?")),
		("name", _("What is this process called?")),
	)
	for key, question in questions:
		if key in words:
			return question
	return _(
		"What is this process called, who or what starts it, and what does it look like when it is finished?"
	)


def redirect_output(conversation: str, instance=None) -> dict:
	"""Answer from the company documents when they cover the question, else decline in the redirect prompt's words."""
	turn = get_turn(conversation)
	subs = prosally_config().get("sub_prompts") or {}
	decline = (subs.get("redirect") or {}).get("prompt") or _(
		"I'm here to help with process modelling. I'm not able to help with that request."
	)
	output = dms_answer_output(conversation, turn.get("user_text") or "", instance) or {
		"intent": "IRRELEVANT",
		"action_intent": None,
		"response": decline,
		"options": [],
	}
	update_turn(conversation, output=output, done=True)
	return {"response": output["response"]}


def no_stage_reply(conversation: str) -> dict:
	"""Close a turn no stage answered as a failure the person can see and the run records."""
	message = _(
		"I lost this reply: the step that should have answered you never ran (NO_STAGE_REPLY). "
		"Please send your message again."
	)
	update_turn(
		conversation,
		output={"intent": "ERROR", "action_intent": None, "response": message, "options": []},
		tool_error={"tool": "finalize", "error": "no stage wrote a reply", "error_code": NO_STAGE_REPLY},
		done=True,
	)
	frappe.log_error(title="ProsAlly finalize: no stage reply", message=f"conversation={conversation}")
	return {
		"error": "NO_STAGE_REPLY: no stage wrote a reply",
		"error_code": NO_STAGE_REPLY,
		"retryable": False,
	}
