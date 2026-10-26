"""Let the agent-creation map take back an agent in Needs Attention or Live.

The start event accepted only a chat agent in Draft, so a re-provisioned agent waited
at it for ever. Prompt generation now runs only for an agent that started as Draft,
Validate stops requiring a prompt from a Background agent, and Save Generated Prompt
only fills an empty prompt. A condition or script someone has changed is reported, not overwritten.
"""

import html
import re

import frappe

START_CONDITIONS_REPLACED = (
	'agent_type=="Chat" and lifecycle_status=="Draft"',
	'agent_type=="Chat" and lifecycle_status in ("Draft", "Needs Attention", "Live")',
)
START_CONDITION = (
	'(agent_type=="Chat" and lifecycle_status=="Draft") or lifecycle_status in ("Needs Attention", "Live")'
)
GENERATE_CONDITION_REPLACED = '(prompt_check or {}).get("needs_prompt") == True'
GENERATE_CONDITION = GENERATE_CONDITION_REPLACED + ' and lifecycle_status == "Draft"'

VALIDATE_CALL_REPLACED = "validate_agent_config(context_docname)"
VALIDATE_CALL = (
	"validate_agent_config(context_docname, require_prompt=frappe.db.get_value("
	'"AI Agent Configuration", context_docname, "agent_type") != "Background")'
)
SAVE_GUARD_REPLACED = "if _p:"
SAVE_GUARD = 'if _p and not frappe.db.get_value("AI Agent Configuration", context_docname, "system_prompt"):'

START_CONDITION_RE = re.compile(
	r"(<bpmn:startEvent\b.*?<bpmn:condition\b[^>]*>)(.*?)(</bpmn:condition>)", re.S
)
GENERATE_FLOW_RE = re.compile(
	r'(<bpmn:sequenceFlow\b[^>]*targetRef="gen_prompt"[^>]*>\s*<bpmn:conditionExpression\b[^>]*>)(.*?)(</bpmn:conditionExpression>)',
	re.S,
)


def execute():
	from one_bpmn.agents.agent_config_resolver import get_creation_process_model

	model = get_creation_process_model()
	if not model:
		print("No agent-creation map on this site; nothing to change")
		return

	xml = frappe.db.get_value("BPMN Process Model", model, "bpmn_xml") or ""
	new_xml, notes = updated_map(xml)
	for note in notes:
		print(f"{model}: {note}")
	if new_xml != xml:
		frappe.db.set_value("BPMN Process Model", model, "bpmn_xml", new_xml, update_modified=False)
		_recompile(model)

	for task_id, replaced, replacement in (
		("validate", VALIDATE_CALL_REPLACED, VALIDATE_CALL),
		("save_prompt", SAVE_GUARD_REPLACED, SAVE_GUARD),
	):
		script = _server_script_of(new_xml, task_id)
		if not script or not frappe.db.exists("Server Script", script):
			print(f"{model}: task {task_id} has no Server Script on this site")
			continue
		body = frappe.db.get_value("Server Script", script, "script") or ""
		new_body, note = updated_script(body, replaced, replacement)
		print(f"{script}: {note}")
		if new_body != body:
			frappe.db.set_value("Server Script", script, "script", new_body, update_modified=False)


def updated_map(xml: str) -> tuple[str, list[str]]:
	"""The map with the new start and prompt-generation conditions, and what was done."""
	notes = []
	xml, note = _swap(xml, START_CONDITION_RE, START_CONDITIONS_REPLACED, START_CONDITION, "start condition")
	notes.append(note)
	xml, note = _swap(
		xml,
		GENERATE_FLOW_RE,
		(GENERATE_CONDITION_REPLACED,),
		GENERATE_CONDITION,
		"prompt generation condition",
	)
	notes.append(note)
	return xml, notes


def updated_script(body: str, replaced: str, replacement: str) -> tuple[str, str]:
	"""The script with one known line changed, and what was done."""
	if replacement in body:
		return body, "already updated"
	if body.count(replaced) != 1:
		return body, f"left as it is: expected {replaced!r} exactly once"
	return body.replace(replaced, replacement), "updated"


def _swap(xml: str, pattern: re.Pattern, replaced: tuple, replacement: str, label: str) -> tuple[str, str]:
	match = pattern.search(xml)
	if not match:
		return xml, f"{label} not found"
	current = html.unescape(match.group(2)).strip()
	if current == replacement:
		return xml, f"{label} already updated"
	if current not in replaced:
		return xml, f"{label} left as it is, because it was customised: {current}"
	start, end = match.span(2)
	return xml[:start] + replacement + xml[end:], f"{label} updated"


def _server_script_of(xml: str, task_id: str) -> str:
	match = re.search(rf'<bpmn:scriptTask\b[^>]*\bid="{task_id}"[^>]*>', xml)
	name = match and re.search(r'serverScript="([^"]+)"', match.group(0))
	return html.unescape(name.group(1)) if name else ""


def _recompile(model: str) -> None:
	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(model)
		print(f"{model}: recompiled")
	except frappe.ValidationError:
		# A map this site cannot compile must not stop the migration; its runs keep the old compiled copy.
		frappe.log_error(title=f"Agent-creation map not recompiled: {model}", message=frappe.get_traceback())
		print(f"{model}: NOT recompiled, see the Error Log; recompile it by hand")
