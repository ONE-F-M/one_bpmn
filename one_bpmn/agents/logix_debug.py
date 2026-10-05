"""Logix's debug path: explain why an existing script fails and propose the smallest fix as a diff.

Build Context calls debug_inputs to put the script and its last error on the turn; the
"Logix - Tool Debug Script" stage calls run_debug_stage, which writes the turn's reply itself.
"""

import difflib
import json
import re

import frappe
from frappe import _

from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.llm_provider.structured_output import provider_schema
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.security.script_validator import validate_script

AGENT_ID = "logix_agent"
CODE_FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)
TRACEBACK = "Traceback (most recent call last)"
ERROR_CHARS = 3000
ENGINE_ERROR_TITLE = 'BPMN ScriptTask: "{}" execution failed'

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


def debug_inputs(user_text: str, original_script_content: str, current_script: str) -> dict:
	"""The script under debug and its last error; what the person pasted wins over the linked script."""
	user_text = user_text or ""
	script_text = original_script_content or ""
	for block in CODE_FENCE.findall(user_text):
		if TRACEBACK not in block:
			script_text = block.strip()
			break

	at = user_text.find(TRACEBACK)
	last_error = user_text[at:] if at != -1 else _logged_error(current_script)
	return {"script_text": script_text, "last_error": last_error[-ERROR_CHARS:]}


def _logged_error(script_name: str) -> str:
	if not script_name:
		return ""
	rows = frappe.get_all(
		"Error Log",
		filters={"method": ENGINE_ERROR_TITLE.format(script_name)},
		fields=["error"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0].error if rows else ""


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
