"""Logix's refusal names the safety rule a blocked script broke and quotes the line.

The review step keeps the gate's findings (rule, line, code) and the reviewer's suggestions on the
turn; finalize turns them into the reply instead of one fixed sentence. The reviewer prompt asks for
the safe alternative in its suggestions. Each anchor must be found exactly once; a script that does
not carry them is logged and left as it is. Idempotent by each script's marker.
"""

import frappe

REVIEW_SCRIPT = "Logix – Tool Review Script"
REVIEW_MARKER = "review_suggestions="
REVIEW_EDITS = (
	("candidate = draft\nif review_raw:", "_review = None\ncandidate = draft\nif review_raw:"),
	(
		"        update_turn(context_docname, violations=_violations, script_safe=False, security_retries=retries)\n",
		"        _review_suggestions = []\n"
		"        if isinstance(_review, dict):\n"
		'            for _s in _review.get("suggestions") or []:\n'
		"                _review_suggestions.append(str(_s))\n"
		'        update_turn(context_docname, violations=_violations, findings=_vres.get("findings") or [],\n'
		"                    review_suggestions=_review_suggestions, script_safe=False, security_retries=retries)\n",
	),
	(
		"update_turn(context_docname, final=candidate, modified_code=code, script_safe=True, violations=[])",
		"update_turn(context_docname, final=candidate, modified_code=code, script_safe=True, violations=[], findings=[])",
	),
	(
		'        result["violations"] = _violations\n',
		'        result["violations"] = _violations\n        result["findings"] = _vres.get("findings") or []\n',
	),
)

FINALIZE_SCRIPT = "Logix – Tool Finalize"
FINALIZE_MARKER = "_refusal = _REFUSAL"
FINALIZE_EDITS = (
	(
		'    if not turn.get("script_safe") and (not _final_text or "```python" in _final_text):\n',
		"    _refusal = _REFUSAL\n"
		'    if turn.get("findings"):\n'
		'        _lines = ["I could not publish this script because the safety check blocks it:"]\n'
		'        for _f in turn.get("findings"):\n'
		'            _ln = "- " + str(_f.get("rule"))\n'
		'            if _f.get("code"):\n'
		'                _ln += " (line " + str(_f.get("line")) + ": `" + str(_f.get("code")) + "`)"\n'
		"            _lines.append(_ln)\n"
		'        if turn.get("review_suggestions"):\n'
		'            _lines.append("")\n'
		'            _lines.append("A safe way to do it: " + " ".join(turn.get("review_suggestions")))\n'
		'        _lines.append("")\n'
		'        _lines.append("Rephrase the request without that step, or tell me why the step is needed '
		'so I can find a safe way to do it.")\n'
		'        _refusal = "\\n".join(_lines)\n'
		'    if not turn.get("script_safe") and (not _final_text or "```python" in _final_text):\n',
	),
	('"response": _REFUSAL,', '"response": _refusal,'),
)

REVIEWER_EDIT = (
	'"suggestions": ["..."],',
	'"suggestions": ["for each security issue, the safe way to do what that line was for"],',
)
REVIEWER_AGENT_ID = "logix_script_reviewer"
MAIN_AGENT_ID = "logix_agent"


def execute():
	_edit_script(REVIEW_SCRIPT, REVIEW_MARKER, REVIEW_EDITS)
	_edit_script(FINALIZE_SCRIPT, FINALIZE_MARKER, FINALIZE_EDITS)
	_edit_reviewer_prompts()


def _edit_script(script_name: str, marker: str, edits: tuple):
	code = frappe.db.get_value("Server Script", script_name, "script")
	if not code or marker in code:
		return
	if any(code.count(old) != 1 for old, _new in edits):
		frappe.log_error(
			title="logix_blocked_script_names_the_rule: script anchor not found",
			message=f"{script_name} does not carry each anchor exactly once; it is left as it is.",
		)
		return
	for old, new in edits:
		code = code.replace(old, new, 1)
	frappe.db.set_value("Server Script", script_name, "script", code, update_modified=False)


def _edit_reviewer_prompts():
	old, new = REVIEWER_EDIT
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": REVIEWER_AGENT_ID}, "name")
	if name:
		prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
		if prompt.count(old) == 1:
			frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.replace(old, new, 1))

	main = frappe.db.get_value("AI Agent Configuration", {"agent_id": MAIN_AGENT_ID}, "name")
	row = main and frappe.db.get_value(
		"AI Agent Sub Prompt",
		{"parent": main, "sub_agent_id": "script_reviewer"},
		["name", "prompt_text"],
	)
	if row and (row[1] or "").count(old) == 1:
		frappe.db.set_value("AI Agent Sub Prompt", row[0], "prompt_text", row[1].replace(old, new, 1))
