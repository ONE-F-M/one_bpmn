"""ProsAlly and LuCrusher post a plain error reply when their agent task failed, not the previous turn's answer.

Save Response checks the agent task's error code before it picks the reply, and Update Conversation
clears ai_result with the other per-turn variables. Scripts are found by api_method, so a site without
these agents is left alone. Idempotent: each edit applies only once.
"""

import frappe

# api_method of each Save Response script -> bpmn id of the agent task in the same map.
SAVE_RESPONSE = {
	"prosally_save_response": "run_prosally_agent",
	"lucrusher_save_response": "run_lucrusher_agent",
}
UPDATE_CONVERSATION = ("prosally_update_conversation", "lucrusher_update_conversation")

SAVE_ANCHOR = "if isinstance(_out, dict) and _out:"
UPDATE_ANCHOR = 'result["intent"] = ""'
CLEAR_LINE = 'result["ai_result"] = None'


def execute():
	for api_method, bpmn_id in SAVE_RESPONSE.items():
		_edit_script(api_method, SAVE_ANCHOR, error_block(bpmn_id) + SAVE_ANCHOR)
	for api_method in UPDATE_CONVERSATION:
		_edit_script(api_method, UPDATE_ANCHOR, f"{UPDATE_ANCHOR}\n{CLEAR_LINE}")


def error_block(bpmn_id: str) -> str:
	"""Script lines that make the error text the reply when the agent task recorded an error code."""
	return (
		f'_failed = task_data.get("{bpmn_id}_error_code")\n'
		"if _failed:\n"
		f'    _reason = str(task_data.get("{bpmn_id}_error_message") or _failed).strip().rstrip(".")\n'
		'    _agent_text = "The AI provider rejected the request: " + _reason + ". Please try again in a few minutes."\n'
		'    _out = {"intent": "ERROR", "response": _agent_text}\n'
	)


def apply_edit(script: str, anchor: str, replacement: str) -> str | None:
	"""Return the script with anchor replaced once, the script unchanged if already edited, or None if the anchor is not unique."""
	if replacement in script:
		return script
	if script.count(anchor) != 1:
		return None
	return script.replace(anchor, replacement, 1)


def _edit_script(api_method: str, anchor: str, replacement: str):
	name = frappe.db.get_value("Server Script", {"api_method": api_method}, "name")
	if not name:
		return
	doc = frappe.get_doc("Server Script", name)
	edited = apply_edit(doc.script or "", anchor, replacement)
	if edited is None:
		frappe.log_error(
			title="chat_agents_post_failed_turn_error: anchor not found",
			message=f"{name} has no single '{anchor}' line; the script is left as-is.",
		)
		return
	if edited != doc.script:
		doc.script = edited
		doc.save(ignore_permissions=True)
