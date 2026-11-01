"""ProsAlly diagnoses a pasted error or a lint finding and says what to change, instead of declining it as off topic.

Edits the live Classify Intent Server Script and the intent_classifier sub-prompt by anchor, and adds the
error_diagnoser sub-prompt. Text that already has its marker is left alone.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_relayouts_and_compares import AGENT_ID, SCRIPT, apply_edits

SUB_AGENT_ID = "error_diagnoser"

SCRIPT_EDITS = (
	(
		"compare_output, relayout_output, ",
		"compare_output, diagnose_output, relayout_output, ",
	),
	(
		'frozenset({"IRRELEVANT", "RELAYOUT", "COMPARE"})',
		'frozenset({"IRRELEVANT", "RELAYOUT", "COMPARE", "DIAGNOSE"})',
	),
	(
		'    if intent == "COMPARE":\n',
		'    if intent == "DIAGNOSE":\n'
		"        update_turn(\n"
		"            context_docname,\n"
		'            output=diagnose_output(current_xml, _scope_texts, turn.get("lint_issues") or []),\n'
		"            done=True,\n"
		"        )\n"
		'        result["next"] = "finalize"\n'
		'    elif intent == "COMPARE":\n',
	),
)
SCRIPT_MARKER = "diagnose_output"

PROMPT_EDITS = (
	(
		"- Anything outside process modelling scope is IRRELEVANT.\n",
		"- Anything outside process modelling scope is IRRELEVANT.\n"
		"- An error message, error log, traceback or lint finding about a process, a step or a script, or a request "
		"to explain or diagnose one, is in scope: classify as DIAGNOSE, never IRRELEVANT. A request to fix lint "
		"findings that asks nothing about the cause stays MODIFY_EXISTING.\n",
	),
	(
		"For AMBIGUOUS, INCOMPLETE, IRRELEVANT, and COMPARE, leave",
		"For AMBIGUOUS, INCOMPLETE, IRRELEVANT, COMPARE, and DIAGNOSE, leave",
	),
	("RELAYOUT|COMPARE|AMBIGUOUS", "RELAYOUT|COMPARE|DIAGNOSE|AMBIGUOUS"),
)
PROMPT_MARKER = "classify as DIAGNOSE"

DIAGNOSER_PROMPT = """You diagnose an error in a process map. You get a JSON object with the pasted "error" text, the "lint_findings" for the elements it names, and the BPMN XML of those "elements".

Find the cause and say what to change. Reply with one JSON object and nothing else:
{"origin": "map" | "server_script" | "unknown", "element_id": "", "root_cause": "", "fix_steps": []}

- origin is "map" when the cause is how a task, event, gateway or flow is configured: a gateway condition that does not evaluate, a missing assignee, a wrong event definition, a flow that goes nowhere.
- origin is "server_script" when the error is raised by the code of a Server Script, for example a traceback through a script task. The script must change, not the map.
- origin is "unknown" when the text does not show the cause. Say in root_cause what is missing.
- element_id is the id of the element at fault, or "" when there is none.
- root_cause is two or three plain sentences for a process owner: what goes wrong and why. No function names.
- fix_steps are short, concrete instructions naming the element and the setting to change. For "server_script", say what the script must do differently. Leave it empty when origin is "unknown"."""


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		_edit_script()
		_edit_agent()
	finally:
		frappe.set_user(original_user)


def _edit_script():
	if not frappe.db.exists("Server Script", SCRIPT):
		return
	doc = frappe.get_doc("Server Script", SCRIPT)
	if SCRIPT_MARKER in (doc.script or ""):
		return
	edited = apply_edits(doc.script or "", SCRIPT_EDITS)
	if edited is None:
		frappe.log_error(
			title="prosally_diagnoses_errors: anchor not found",
			message="The Classify Intent script does not contain every expected anchor.",
		)
		return
	doc.script = edited
	doc.save(ignore_permissions=True)


def _edit_agent():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	agent = frappe.get_doc("AI Agent Configuration", name)
	changed = False
	for row in agent.sub_prompts:
		if row.sub_agent_id != "intent_classifier" or PROMPT_MARKER in (row.prompt_text or ""):
			continue
		edited = apply_edits(row.prompt_text or "", PROMPT_EDITS)
		if edited is None:
			frappe.log_error(
				title="prosally_diagnoses_errors: anchor not found",
				message="The intent_classifier prompt does not contain every expected anchor.",
			)
			continue
		row.prompt_text = edited
		changed = True
	if not any(row.sub_agent_id == SUB_AGENT_ID for row in agent.sub_prompts):
		agent.append(
			"sub_prompts",
			{"sub_agent_id": SUB_AGENT_ID, "sub_agent_name": "Error Diagnoser", "prompt_text": DIAGNOSER_PROMPT},
		)
		changed = True
	if changed:
		agent.save(ignore_permissions=True)
