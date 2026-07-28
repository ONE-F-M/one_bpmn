"""
WI-001751: stop the AI Assistant's response contract from killing tool turns.

Symptom: asked to build evals, the assistant called list_eval_suites, called
create_eval_suite (which committed a real suite), then replied "Great! Now I'll
add the 3 test cases:" — and the whole turn errored with
SCHEMA_VALIDATION_FAILED. The suite survived, the reply did not, so the next turn
could not see what it had done: it re-asked its questions and later created a
second, empty suite. That is where the duplicate suites and the "assistant was
not aware it created an eval suite" came from.

Cause: the assistant's ai_agent_task carried aiResponseFormat="json" with a
required {needs_tool, final_answer} schema, and three contracts were disagreeing
about the reply shape:

  * the shape's aiUserPrompt (inherited from the chat-map template) ordered
    {"needs_tool": bool, "final_answer": str};
  * the assistant configuration's REPLY FORMAT section orders
    {"message", "recommendations"} on task-dialog turns;
  * api/ai_assistant.recommend_ai_task_config, the only consumer, reads
    message / recommendations / proposed_config — it never reads needs_tool or
    final_answer, and falls back to treating a non-JSON reply as the message.

So the consumer was already tolerant of prose while the executor hard-failed on
it, and the needs_tool flag was vestigial: since the Durable HITL work the step
loop decides when tools run, not a flag in the reply.

This patch removes aiResponseFormat / aiResponseSchema from that shape and drops
the now-false OUTPUT PROTOCOL paragraph from its user prompt, leaving one
contract — the configuration's — and letting _extract_json parse it when present.

It also adds a prompt line for the second half of the failure: the model announced
work it had not done. Tool calls belong in the turn that promises them.

Only the assistant's own map is touched; other agents keep their contracts.
Diagrams are data, never code (WI-001540), so the change is applied to the site's
copy. Idempotent.
"""

import re

import frappe

MODEL_NAME = "AI Agent Assistant — Chat"
AGENT_ID = "ai_agent_assistant"
TASK_ID = "ai_agent_task"

# The paragraph the chat-map template bakes into the user prompt. It orders a
# reply shape nothing consumes, and contradicts the configuration's REPLY FORMAT.
_OUTPUT_PROTOCOL_RE = re.compile(
	r"\s*OUTPUT PROTOCOL \(non-negotiable\):.*?(?=&#10;&#10;|\Z)", re.S
)

_PROMPT_MARKER = "ACT IN THE TURN YOU PROMISE:"
_PROMPT_SECTION = """

ACT IN THE TURN YOU PROMISE:
  - Never announce work you have not done. "Now I'll add the test cases" followed by no tool call leaves the designer with a half-built suite and you with no record of it — make the calls, then report what exists.
  - You may call several tools in one turn. When you have agreed a suite and three cases, create the suite and all three cases before you reply.
  - Report only what the tool results actually confirm. If a call returned an error, say so plainly rather than describing the outcome you intended."""


def _strip_response_contract(task_xml: str) -> str:
	"""Remove the JSON response format/schema and the stale output protocol."""
	out = re.sub(r'\s*spiffworkflow:aiResponseFormat="[^"]*"', "", task_xml)
	out = re.sub(r'\s*spiffworkflow:aiResponseSchema="[^"]*"', "", out)

	user_prompt = re.search(r'spiffworkflow:aiUserPrompt="(.*?)"', out, re.S)
	if user_prompt:
		cleaned = _OUTPUT_PROTOCOL_RE.sub("", user_prompt.group(1))
		if cleaned != user_prompt.group(1):
			out = out[: user_prompt.start(1)] + cleaned + out[user_prompt.end(1):]
	return out


def _update_process_model() -> None:
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	task = re.search(rf'<bpmn:serviceTask id="{TASK_ID}"[^>]*>', xml)
	if not task:
		frappe.log_error(
			title="fix_assistant_response_contract: agent task not found",
			message=f"'{MODEL_NAME}' has no '{TASK_ID}' service task; the response "
					"contract was left as it is.",
		)
		return

	updated_task = _strip_response_contract(task.group(0))
	if updated_task == task.group(0):
		return

	xml = xml[: task.start()] + updated_task + xml[task.end():]
	# db_set skips the editability gate — a trusted content migration, the same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="fix_assistant_response_contract: recompile failed",
			message=frappe.get_traceback(),
		)


def _steer_prompt() -> None:
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if _PROMPT_MARKER in prompt:
		return
	frappe.db.set_value(
		"AI Agent Configuration",
		name,
		"system_prompt",
		prompt.rstrip() + _PROMPT_SECTION,
		update_modified=False,
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def execute():
	_update_process_model()
	_steer_prompt()
	frappe.db.commit()
