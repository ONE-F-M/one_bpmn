"""ProsAlly changes the inside of a sub-process when the request is about one, and says so when nothing changed.

Edits the Build Context and Tool Modify Process scripts and the node-types skill in place. One already
carrying the change is skipped, and one whose anchors are not each found exactly once is logged and left as it is.
"""

import frappe

MODIFY_IMPORT = (
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, ",
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, resolve_scope, splice_subprocess, ",
)
MODIFY_SCOPE = (
	'current_xml = turn.get("current_xml", "")\n',
	r'''current_xml = turn.get("current_xml", "")
_scope_texts = [turn.get("user_text", "")]
for _m in reversed(chat_history):
    if (_m.get("role") or _m.get("type")) == "user":
        _scope_texts.append(_m.get("content") or "")
scope = resolve_scope(current_xml, _scope_texts, turn.get("scope_id", ""))
''',
)
MODIFY_PROMPT = (
	'initial_prompt = "\\n\\n".join(_parts)\n',
	r'''initial_prompt = "\n\n".join(_parts)
if scope:
    initial_prompt = "\n\n".join([
        "Action: MODIFY_EXISTING - the request is about the sub-process \"" + scope["name"] + "\" (id " + scope["id"] + ") only.",
        "Output the IR JSON for the steps INSIDE this sub-process and nothing else: its own startEvent, its steps and flows, and its endEvent. Do NOT output the sub-process node itself, the rest of the process, or lanes. Flows join only steps inside it. Keep the exact IDs of the steps listed below that stay.",
        "Modification request from conversation:\n" + _hist,
        "Latest message: " + turn.get("user_text", ""),
        "ELEMENT ID TABLE (inside the sub-process):\n" + extract_element_ids(scope["xml"]),
        "Current XML of the sub-process:\n" + scope["xml"],
        "Output the complete IR JSON for the inside of the sub-process now.",
    ])
''',
)
MODIFY_SPLICE = (
	"    merged_xml, removed_elements = transfer_properties(current_xml, best_xml)\n",
	"""    if scope and best_xml:
        best_xml = splice_subprocess(current_xml, best_xml, scope["id"])
    merged_xml, removed_elements = transfer_properties(current_xml, best_xml)
""",
)
MODIFY_REPLY_VARS = (
	'        output = {\n            "intent": "BPMN_MODIFIED",',
	r'''        _changes = describe_changes(current_xml, merged_xml)
        _where = ("sub-process \"" + scope["name"] + "\"") if scope else (xml_name + " process")
        if "\n- " in _changes:
            _reply = ("I've updated the " + _where + "." + note + " All existing configurations have been preserved. Review the changes on the canvas.") + _changes + describe_task_config(merged_xml, current_xml)
        else:
            _reply = _changes.strip() + note
        output = {
            "intent": "BPMN_MODIFIED",''',
)
MODIFY_REPLY = (
	"""            "response": (
                "I've updated the " + xml_name + " process." + note + " All existing configurations "
                "have been preserved. Review the changes on the canvas."
            ) + describe_changes(current_xml, merged_xml) + describe_task_config(merged_xml, current_xml),
""",
	'            "response": _reply,\n',
)
CLASSIFY_IMPORT = (
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, join_confirmation, ",
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, join_confirmation, resolve_scope, ",
)
CLASSIFY_SCOPE = (
	'    _hist = format_history(turn.get("chat_history"))\n',
	r'''    _hist = format_history(turn.get("chat_history"))
    _scope_texts = [message]
    for _m in reversed(turn.get("chat_history") or []):
        if (_m.get("role") or _m.get("type")) == "user":
            _scope_texts.append(_m.get("content") or "")
    scope = resolve_scope(current_xml, _scope_texts, turn.get("scope_id", ""))
''',
)
CLASSIFY_HINT = (
	'    _parts.append("User message: " + message)\n',
	r'''    if scope:
        _parts.append("The diagram already has the sub-process \"" + scope["name"] + "\" and this request is about it. Classify it as MODIFY_EXISTING and describe it as updating that sub-process.")
    _parts.append("User message: " + message)
''',
)
CLASSIFY_GUARD = (
	'    if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | frozenset({"IRRELEVANT"})):\n        intent = "INCOMPLETE"\n',
	'    if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | frozenset({"IRRELEVANT"})):\n        intent = "INCOMPLETE"\n'
	'    if scope and intent in _GENERATE_INTENTS:\n        intent = "MODIFY_EXISTING"\n',
)
CONTEXT_KEYS = (
	"for _k in ['process_name', 'diagram_name', 'confirmed_action', 'current_xml']:",
	"for _k in ['process_name', 'diagram_name', 'confirmed_action', 'current_xml', 'scope_id']:",
)
CONTEXT_TURN = (
	'    "current_xml": task_data.get("current_xml", "") or "",\n})',
	'    "current_xml": task_data.get("current_xml", "") or "",\n    "scope_id": task_data.get("scope_id", "") or "",\n})',
)
SKILL_EVENTS = (
	"- endEvent: at least one; no outgoing flows; the process is done.\n",
	"- endEvent: at least one; no outgoing flows; the process is done.\n"
	"- intermediateCatchEvent: the process WAITS here for something to happen, such as a timer or a message. One incoming and one outgoing flow.\n"
	"- intermediateThrowEvent: the process signals something and moves straight on. One incoming and one outgoing flow.\n",
)
SKILL_SUBPROCESS = (
	"- subProcess: a group of steps collapsed into one named box.",
	'- subProcess: a group of steps collapsed into one named box. Put its steps in "children": {"nodes": [...], "flows": [...]}, '
	"with their own startEvent and endEvent. Flows inside children join only the steps inside it, and flows outside never name a step inside it.",
)

# Server Script name pattern -> (field, edits, marker of an applied change).
SCRIPTS = {
	"ProsAlly%Build Context": ("script", (CONTEXT_KEYS, CONTEXT_TURN), "scope_id"),
	"ProsAlly%Tool Classify Intent": (
		"script",
		(CLASSIFY_IMPORT, CLASSIFY_SCOPE, CLASSIFY_HINT, CLASSIFY_GUARD),
		"resolve_scope(",
	),
	"ProsAlly%Tool Modify Process": (
		"script",
		(MODIFY_IMPORT, MODIFY_SCOPE, MODIFY_PROMPT, MODIFY_SPLICE, MODIFY_REPLY_VARS, MODIFY_REPLY),
		"resolve_scope(",
	),
}
SKILL = "prosally-node-types-and-flow-rules"


def execute():
	for pattern, (field, edits, marker) in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			_apply("Server Script", name, field, edits, marker)
	if frappe.db.exists("AI Skill", SKILL):
		_apply("AI Skill", SKILL, "body", (SKILL_EVENTS, SKILL_SUBPROCESS), "intermediateCatchEvent")


def _apply(doctype: str, name: str, field: str, edits: tuple, marker: str) -> None:
	doc = frappe.get_doc(doctype, name)
	text = doc.get(field) or ""
	if marker in text:
		return
	edited = with_edits(text, edits)
	if edited is None:
		frappe.log_error(
			title="prosally_scope_modify_to_subprocess: anchors not found",
			message=f"{doctype} {name} does not carry each anchor exactly once; it is left as it is.",
		)
		return
	doc.set(field, edited)
	doc.save(ignore_permissions=True)


def with_edits(text: str, edits: tuple) -> str | None:
	"""text with every (anchor, replacement) applied, or None if an anchor is not found exactly once."""
	if any(text.count(anchor) != 1 for anchor, _ in edits):
		return None
	for anchor, replacement in edits:
		text = text.replace(anchor, replacement, 1)
	return text
