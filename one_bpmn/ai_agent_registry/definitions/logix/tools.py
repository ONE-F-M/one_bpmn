"""Logix's tool functions: the debug stage and read-only Server Script lookups."""

import difflib
import json

import frappe
from frappe import _

from one_bpmn.ai_agent_registry.definitions.shared.helpers import tool_envelope
from one_bpmn.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.ai_agent_security.code_checks.script_validator import validate_script
from one_bpmn.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings
from one_bpmn.processa_engine.agent_runtime.structured_output import provider_schema
from one_bpmn.processa_engine.agent_runtime.turn_state import get_turn, run_sync, update_turn

AGENT_ID = "logix_agent"

DEBUG_SCHEMA = {
	"type": "object",
	"properties": {"explanation": {"type": "string"}, "fixed_script": {"type": "string"}},
	"required": ["explanation", "fixed_script"],
}
REVIEW_SCHEMA = {
	"type": "object",
	"properties": {
		"approved": {"type": "boolean"},
		"issues": {"type": "array", "items": {"type": "string"}},
		"suggestions": {"type": "array", "items": {"type": "string"}},
	},
	"required": ["approved", "issues", "suggestions"],
}


def run_debug_stage(conversation: str) -> dict:
	"""Diagnose, propose a minimal fix, review only the diff, then gate the fixed script."""
	turn = get_turn(conversation)
	script = turn.get("script_text") or ""
	if not script:
		return _reply(
			conversation,
			_("Paste the script that fails, and the error if you have one, and I will look at it."),
		)

	config = get_agent_config(AGENT_ID) or {}
	config.setdefault("agent_id", AGENT_ID)
	subs = config.get("sub_prompts") or {}
	adapter = get_llm_adapter_from_settings(config)
	shape_kind = (turn.get("process_context") or {}).get("shape_kind") or "script_task"

	debugger = (subs.get("script_debugger") or {}).get("prompt") or ""
	debug = _ask(adapter, debugger, _debug_prompt(turn, shape_kind), DEBUG_SCHEMA)
	fixed = (debug.get("fixed_script") or "").strip()
	explanation = debug.get("explanation") or ""
	diff = "".join(
		difflib.unified_diff(
			script.splitlines(keepends=True),
			(fixed + "\n").splitlines(keepends=True),
			fromfile="your script",
			tofile="with the fix",
		)
	)
	if not fixed or not diff:
		return _reply(conversation, explanation)

	review = _ask(
		adapter, _reviewer_system(subs, shape_kind), _review_prompt(shape_kind, diff), REVIEW_SCHEMA
	)
	gate = validate_script(fixed)
	if review.get("approved") and gate["valid"]:
		return _reply(conversation, explanation, original=script, fixed=fixed, diff=diff)

	lines = [explanation, "", _("I drafted a fix, but it does not pass review, so I am not offering it:")]
	lines += [f"- {issue}" for issue in review.get("issues") or []]
	lines += [f"- {f['rule']} (line {f['line']}: `{f['code']}`)" for f in gate.get("findings") or []]
	return _reply(conversation, "\n".join(lines))


def _ask(adapter, system: str, user: str, schema: dict) -> dict:
	step = run_sync(
		adapter.step(
			system=system,
			transcript=[{"role": "user", "content": user}],
			response_schema=provider_schema(schema),
		)
	)
	return json.loads(step.content)


def _debug_prompt(turn: dict, shape_kind: str) -> str:
	parts = [f"Shape kind: {shape_kind}", f"The script:\n```python\n{turn.get('script_text')}\n```"]
	if turn.get("last_error"):
		parts.append(f"The last error it raised:\n```\n{turn['last_error']}\n```")
	parts.append(f"What the person says: {turn.get('user_text') or ''}")
	return "\n\n".join(parts)


def _reviewer_system(subs: dict, shape_kind: str) -> str:
	contract = "bpmn-agent-tool-contract" if shape_kind == "agent_tool" else "bpmn-script-task-contract"
	return (
		((subs.get("script_reviewer") or {}).get("prompt") or "")
		+ "\n\n# The contract this draft must follow\n"
		+ (frappe.db.get_value("AI Skill", contract, "body") or "")
		+ "\n\n# The safety rules the gate enforces\n"
		+ (frappe.db.get_value("AI Skill", "frappe-server-script-safety", "body") or "")
	)


def _review_prompt(shape_kind: str, diff: str) -> str:
	return (
		f"Shape kind: {shape_kind}\n\n"
		"This is a fix to an existing script, given as a unified diff. Review only the lines it adds or "
		"removes; the rest of the script is not part of this change. Leave revised_script out.\n\n"
		f"```diff\n{diff}```"
	)


def _reply(conversation: str, response: str, original: str = "", fixed: str = "", diff: str = "") -> dict:
	output = {
		"intent": "MODIFY" if diff else "DEBUG_EXISTING",
		"response": response,
		"diff": diff or None,
		"original_script": original or None,
		"modified_script": fixed or None,
		"options": None,
		"suggested_name": None,
	}
	update_turn(conversation, output=output, done=True, script_safe=bool(diff))
	return {"has_fix": bool(diff)}


@tool_envelope(
	"Logix Tool - get_server_script_content",
	lambda script_name: f"# Error: Failed to fetch Server Script '{script_name}'.",
)
def get_server_script_content(script_name: str) -> str:
	"""The Python source of a Server Script, or a message starting "# Error:" when it cannot be read."""
	try:
		doc = frappe.get_doc("Server Script", script_name)
		if not doc.script:
			return f"# Script '{script_name}' exists but has no content yet."
		return doc.script
	except frappe.DoesNotExistError:
		return f"# Error: Server Script '{script_name}' not found."
	except frappe.PermissionError:
		return f"# Error: No permission to read Server Script '{script_name}'."


@tool_envelope(
	"Logix Tool - get_server_script_meta",
	lambda script_name: json.dumps({"error": f"Failed to fetch metadata for '{script_name}'."}),
)
def get_server_script_meta(script_name: str) -> str:
	"""A Server Script's type, DocType, event, API method and disabled flag, as JSON."""
	try:
		doc = frappe.get_doc("Server Script", script_name)
		return json.dumps({
			"name": doc.name,
			"script_type": doc.script_type,
			"reference_doctype": doc.reference_doctype or "",
			"doctype_event": doc.doctype_event or "",
			"api_method": doc.api_method or "",
			"disabled": bool(doc.disabled),
		})
	except frappe.DoesNotExistError:
		return json.dumps({"error": f"Server Script '{script_name}' not found."})


@tool_envelope("Logix Tool - list_api_server_scripts", lambda: json.dumps([]))
def list_api_server_scripts() -> str:
	"""The names of the enabled API Server Scripts, as a JSON array."""
	scripts = frappe.get_all(
		"Server Script",
		filters={"script_type": "API", "disabled": 0},
		fields=["name"],
		limit_page_length=100,
		order_by="name asc",
	)
	return json.dumps([s.name for s in scripts])
