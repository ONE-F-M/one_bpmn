"""ProsAlly answers a question about company documents instead of declining it, and names the documents it checked when it draws.

Edits the live Redirect and Save Response Server Scripts by anchor. Text that already has its marker is left alone.
"""

import frappe

from processa.patches.v1_0.prosally_relayouts_and_compares import DASH, apply_edits

REDIRECT_SCRIPT = f"ProsAlly {DASH} Tool Redirect"
SAVE_SCRIPT = f"ProsAlly {DASH} Save Response"

REDIRECT_MARKER = "dms_answer_output"
REDIRECT_EDITS = (
	(
		'output = {"intent": "IRRELEVANT", "action_intent": None, "response": msg, "options": []}\n'
		"update_turn(context_docname, output=output, done=True)\n"
		'result["response"] = msg\n',
		"from processa.agents.prosally_helpers import dms_answer_output\n"
		'output = dms_answer_output(context_docname, turn.get("user_text") or "", instance)\n'
		"if not output:\n"
		'    output = {"intent": "IRRELEVANT", "action_intent": None, "response": msg, "options": []}\n'
		"update_turn(context_docname, output=output, done=True)\n"
		'result["response"] = output["response"]\n',
	),
)

SAVE_MARKER = "add_document_sources"
SAVE_EDITS = (
	(
		'msg = frappe.new_doc("Chat Message")\n',
		"from processa.agents.prosally_helpers import add_document_sources\n"
		"response_text = add_document_sources(response_text, intent, _turn)\n"
		'if isinstance(agent_result, dict) and agent_result.get("response"):\n'
		'    agent_result["response"] = response_text\n'
		'msg = frappe.new_doc("Chat Message")\n',
	),
)


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		_edit_script(REDIRECT_SCRIPT, edit_redirect_script)
		_edit_script(SAVE_SCRIPT, edit_save_response)
	finally:
		frappe.set_user(original_user)


def edit_redirect_script(script: str) -> str | None:
	"""The Redirect script that answers from the DMS before it declines; None when its edit point is gone."""
	return script if REDIRECT_MARKER in script else apply_edits(script, REDIRECT_EDITS)


def edit_save_response(script: str) -> str | None:
	"""The Save Response script that names the documents checked in a drawn reply; None when its edit point is gone."""
	return script if SAVE_MARKER in script else apply_edits(script, SAVE_EDITS)


def _edit_script(name: str, editor):
	if not frappe.db.exists("Server Script", name):
		return
	doc = frappe.get_doc("Server Script", name)
	edited = editor(doc.script or "")
	if edited is None:
		frappe.log_error(
			title="prosally_answers_dms_questions: edit point not found",
			message=f"'{name}' no longer contains the text this patch edits; add the change by hand.",
		)
		return
	if edited != doc.script:
		doc.script = edited
		doc.save(ignore_permissions=True)
