"""Logix's agent tool contract and reviewer describe how agent tools run today.

Tools run in one namespace, get task_data and import_script, and import from processa modules.
Each fix is a replacement of the exact stale text, so a text already fixed is left as it is.
"""

import frappe

FIXES = (
	(
		"The tool runs with SPLIT exec globals and locals and receives ONLY these top-level names:",
		"The tool runs in one namespace, like a script task, and receives these top-level names:",
	),
	(
		"\n\nIt does NOT receive workflow variables, and there is NO `task_data`: reading it raises NameError.",
		"\n- `task_data`: the calling agent task's workflow variables with the model's arguments on top. "
		'Read one with `task_data.get("name")`.'
		"\n- `import_script`: calls a library script on the map.",
	),
	(
		"## Hard constraints (the namespace makes these bugs, not style)\n"
		"1. Straight-line code only. Never define a `def` or a `lambda`: with split namespaces a function body "
		"that touches a top-level name dies with NameError when the model calls the tool. Importing and calling "
		"module functions is fine.",
		"## Hard constraints\n"
		'1. `def`, `lambda` and `while` follow the "What the safety check accepts on this site" list. Where it '
		"accepts them, functions can call each other and read top-level names.",
	),
	(
		"A tool sees only its arguments, so `context_docname` is the one bridge to per-turn state",
		"A tool sees its arguments and the calling task's variables but not the conversation, so "
		"`context_docname` is the bridge to per-turn state",
	),
	(
		"- Reads `task_data` or any workflow variable \u2192 NameError at runtime. Rewrite to use the LLM's "
		"declared arguments or the turn-state bridge.\n"
		"- Defines a helper `def` or `lambda` that references a top-level name \u2192 NameError under split "
		"namespaces. Rewrite as straight-line code (imported module functions are fine).\n",
		"- Reads an argument the shape does not declare in aiToolParams. Rewrite to a declared argument or "
		"`task_data.get(...)`. Reading `task_data`, and a `def` or `lambda` the site accepts, are correct; "
		"never rewrite them.\n",
	),
	(
		"(shape_tools synthetic task, SPLIT globals/locals) \u2550\u2550\u2550\n"
		"Injected: the calling LLM's arguments as top-level names, plus `frappe`, `context_doctype`, "
		"`context_docname`, `doc`, `result`. There are NO workflow variables and NO `task_data`.",
		"(shape_tools synthetic task, ONE merged exec namespace) \u2550\u2550\u2550\n"
		"Injected: the calling LLM's arguments as top-level names, plus `frappe`, `context_doctype`, "
		"`context_docname`, `doc`, `result`, and `task_data` (the calling task's workflow variables with the "
		"arguments on top).",
	),
	("one_bpmn.agents.turn_state", "processa.processa_engine.agent_runtime.turn_state"),
	("one_bpmn.agents.shape_tools", "processa.ai_agent_skills.tools.shape_tools"),
)
SKILLS = ("bpmn-agent-tool-contract", "calling-an-ai-agent-from-a-script")


def execute():
	for skill in SKILLS:
		if frappe.db.exists("AI Skill", skill):
			_save_fixed(frappe.get_doc("AI Skill", skill), [("body", None)])
	main = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_agent"}, "name")
	if main:
		config = frappe.get_doc("AI Agent Configuration", main)
		rows = [d for d in config.sub_prompts if d.sub_agent_id == "script_reviewer"]
		_save_fixed(config, [("prompt_text", row) for row in rows])
	reviewer = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_script_reviewer"}, "name")
	if reviewer:
		_save_fixed(frappe.get_doc("AI Agent Configuration", reviewer), [("system_prompt", None)])


def fixed(text: str) -> str:
	"""The text with every stale passage replaced."""
	for old, new in FIXES:
		text = text.replace(old, new)
	return text


def _save_fixed(doc, fields: list) -> None:
	"""Save doc when one of its fields (on itself or a child row) held stale text."""
	changed = False
	for field, row in fields:
		target = row or doc
		text = target.get(field) or ""
		if fixed(text) != text:
			target.set(field, fixed(text))
			changed = True
	if changed:
		doc.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
