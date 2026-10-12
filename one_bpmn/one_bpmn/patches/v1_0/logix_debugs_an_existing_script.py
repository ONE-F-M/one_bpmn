"""Logix gets a debug path: a request to fix a failing script is DEBUG_EXISTING, not a new script.

The classifier learns the intent and routes it to a new debug_script tool. Build Context puts the
script and its last error on the turn. The stage explains the failure, proposes a minimal diff and
reviews only the diff. Each anchor must be found exactly once; anything else is logged and left as it
is. Idempotent by each target's marker.
"""

import frappe

EN_DASH = chr(0x2013)
MODEL_NAME = f"Logix {EN_DASH} Script Task Agent"
MAIN_AGENT = "Logix"
CLASSIFIER_AGENT_ID = "logix_intent_classifier"
BUILD_CONTEXT = f"Logix {EN_DASH} Build Context"
DEBUG_SCRIPT = f"Logix {EN_DASH} Tool Debug Script"
SUB_AGENT_ID = "script_debugger"

DEBUGGER_PROMPT = """You debug a Frappe Server Script that already exists. You get the script, the error it last raised when there is one, and what the person saw.

Find the cause in this script and fix only that. Keep every other line exactly as it is: the same names, order, comments and formatting. Do not rewrite, restyle or extend the script.

The fix follows the same safety rules as any Logix script: no ignore_permissions, no frappe.set_user, no frappe.db.commit, no raw SQL, no imports outside Frappe.

Put in "explanation" two or three plain sentences for a process owner: what goes wrong and what the fix changes. No function names.
Put in "fixed_script" the whole script with the fix applied, without code fences. If the cause is not in this script, return the script unchanged and say in "explanation" what to check next."""

CLASSIFIER_EDIT = (
	'("what does this script do", "why did it fail") is MODIFY',
	'("what does this script do") is MODIFY',
)
CLASSIFIER_RULE = (
	"\n\nDEBUG_EXISTING, which overrides every rule above:\n"
	"- The person says an existing script fails, raises an error or does the wrong thing and wants it working "
	'("this script shows a white screen and then the transaction fails", "why does this throw", a pasted script '
	"with its error). The script is the linked one or one pasted in the request. The intent is DEBUG_EXISTING and "
	'next = "debug_script", whatever the shape kind.\n'
	"- With no script linked and none pasted, it stays DISAMBIGUATE."
)
ORCHESTRATOR_RULE = (
	"\n\nIf next is debug_script, call debug_script, then call finalize and stop. "
	"Never call a writer or review_script on that turn."
)

BUILD_CONTEXT_MARKER = "debug_inputs"
BUILD_CONTEXT_EDITS = (
	(
		"from one_bpmn.agents.turn_state import set_turn\n",
		"from one_bpmn.agents.logix_debug import debug_inputs\nfrom one_bpmn.agents.turn_state import set_turn\n",
	),
	(
		'    "process_context": task_data.get("process_context") or {},\n})',
		'    "process_context": task_data.get("process_context") or {},\n'
		'    **debug_inputs(task_data.get("user_text"), task_data.get("original_script_content"), '
		'task_data.get("current_script")),\n})',
	),
)

DEBUG_SCRIPT_BODY = """# Explains why the existing script fails and proposes the smallest fix as a diff.
from one_bpmn.agents.logix_debug import run_debug_stage
result.update(run_debug_stage(context_docname))
"""

# Raw bpmn_xml text, attribute escaping included.
MAP_MARKER = 'id="debug_script"'
MAP_EDITS = (
	(
		"&#34;enum&#34;: [&#34;CREATE&#34;, &#34;MODIFY&#34;, &#34;DISAMBIGUATE&#34;]",
		"&#34;enum&#34;: [&#34;CREATE&#34;, &#34;MODIFY&#34;, &#34;DISAMBIGUATE&#34;, &#34;DEBUG_EXISTING&#34;]",
	),
	(
		"&#34;enum&#34;: [&#34;clarify&#34;, &#34;write_script&#34;, &#34;write_agent_tool&#34;]",
		"&#34;enum&#34;: [&#34;clarify&#34;, &#34;write_script&#34;, &#34;write_agent_tool&#34;, &#34;debug_script&#34;]",
	),
	(
		"<bpmn:completionCondition",
		f'<bpmn:scriptTask id="debug_script" name="debug_script" spiffworkflow:serverScript="{DEBUG_SCRIPT}" '
		f'spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="{DEBUG_SCRIPT}">\n'
		"        <bpmn:documentation>Explain why the existing script fails and propose the smallest fix as a diff. "
		"Call when next is debug_script, then call finalize.</bpmn:documentation>\n"
		f"        <bpmn:script>{DEBUG_SCRIPT}</bpmn:script>\n"
		"      </bpmn:scriptTask>\n"
		"      <bpmn:completionCondition",
	),
	(
		"</bpmndi:BPMNPlane>",
		'<bpmndi:BPMNShape id="debug_script_di" bpmnElement="debug_script">\n'
		'        <dc:Bounds x="1180" y="570" width="100" height="70" />\n'
		"      </bpmndi:BPMNShape>\n"
		"    </bpmndi:BPMNPlane>",
	),
)


def execute():
	_add_sub_prompt()
	_edit_classifier()
	_append_once("AI Agent Configuration", MAIN_AGENT, ORCHESTRATOR_RULE)
	_create_debug_script()
	_edit_text("Server Script", BUILD_CONTEXT, "script", BUILD_CONTEXT_MARKER, BUILD_CONTEXT_EDITS)
	if _edit_text("BPMN Process Model", MODEL_NAME, "bpmn_xml", MAP_MARKER, MAP_EDITS):
		from one_bpmn.api.compilation import compile_process_model

		compile_process_model(MODEL_NAME)


def _add_sub_prompt():
	if not frappe.db.exists("AI Agent Configuration", MAIN_AGENT):
		return
	doc = frappe.get_doc("AI Agent Configuration", MAIN_AGENT)
	if any(row.sub_agent_id == SUB_AGENT_ID for row in doc.sub_prompts):
		return
	doc.append(
		"sub_prompts",
		{"sub_agent_id": SUB_AGENT_ID, "sub_agent_name": "Script Debugger", "prompt_text": DEBUGGER_PROMPT},
	)
	doc.save(ignore_permissions=True)


def _edit_classifier():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": CLASSIFIER_AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if CLASSIFIER_RULE.strip() in prompt:
		return
	old, new = CLASSIFIER_EDIT
	if prompt.count(old) == 1:
		prompt = prompt.replace(old, new, 1)
	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.rstrip() + CLASSIFIER_RULE)
	frappe.cache.delete_value(f"agent_config:{CLASSIFIER_AGENT_ID}")


def _append_once(doctype: str, name: str, rule: str):
	if not frappe.db.exists(doctype, name):
		return
	prompt, agent_id = frappe.db.get_value(doctype, name, ["system_prompt", "agent_id"])
	if rule.strip() in (prompt or ""):
		return
	frappe.db.set_value(doctype, name, "system_prompt", (prompt or "").rstrip() + rule)
	frappe.cache.delete_value(f"agent_config:{agent_id}")


def _create_debug_script():
	if frappe.db.exists("Server Script", DEBUG_SCRIPT):
		return
	frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": DEBUG_SCRIPT,
			"script_type": "API",
			"api_method": "logix_tool_debug_script",
			"script": DEBUG_SCRIPT_BODY,
		}
	).insert(ignore_permissions=True)


def _edit_text(doctype: str, name: str, field: str, marker: str, edits: tuple) -> bool:
	text = frappe.db.get_value(doctype, name, field)
	if not text or marker in text:
		return False
	if any(text.count(old) != 1 for old, _new in edits):
		frappe.log_error(
			title="logix_debugs_an_existing_script: anchor not found",
			message=f"{doctype} {name} does not carry each anchor exactly once; it is left as it is.",
		)
		return False
	for old, new in edits:
		text = text.replace(old, new, 1)
	frappe.db.set_value(doctype, name, field, text, update_modified=False)
	return True
