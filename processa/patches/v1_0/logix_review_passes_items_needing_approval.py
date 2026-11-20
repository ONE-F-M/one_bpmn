"""Logix's review and finalize steps refuse only a script that does not parse.

Anything else the check finds needs approval: the script is returned and the reply names those items.
Each anchor must be found exactly once; a script without them is logged and left as it is.
"""

import re

import frappe

REVIEW_SCRIPT = "Logix \u2013 Tool Review Script"
FINALIZE_SCRIPT = "Logix \u2013 Tool Finalize"
REVIEW_MARKER = "_needs_approval"
FINALIZE_MARKER = 'if not [_f for _f in _vres.get("findings")'
SYNTAX_ONLY = '[_f for _f in {0}.get("findings") or [] if _f.get("category") == "Syntax error"]'

REVIEW_EDITS = (
	(
		re.compile(
			r'^( *)_violations = _vres\.get\("violations", \[\]\) or \[\]\n\1_valid = bool\(_vres\.get\("valid"\)\)\n',
			re.MULTILINE,
		),
		lambda m: (
			f'{m[1]}_needs_approval = [_f for _f in _vres.get("findings") or [] '
			'if _f.get("category") != "Syntax error"]\n'
			f'{m[1]}_violations = [_f.get("rule") for _f in {SYNTAX_ONLY.format("_vres")}]\n'
			f"{m[1]}_valid = not _violations\n"
		),
	),
	(
		re.compile(r'if bool\(_rev2\.get\("valid"\)\):'),
		lambda m: f"if not {SYNTAX_ONLY.format('_rev2')}:",
	),
	(
		re.compile(
			r"^( *)(update_turn\(context_docname, final=candidate, modified_code=code, script_safe=True)",
			re.MULTILINE,
		),
		lambda m: (
			f"{m[1]}if _needs_approval:\n"
			f"{m[1]}    _items = []\n"
			f"{m[1]}    for _f in _needs_approval:\n"
			f'{m[1]}        _item = str(_f.get("name")) + " (" + str(_f.get("category")) + ")"\n'
			f"{m[1]}        if _item not in _items:\n"
			f"{m[1]}            _items.append(_item)\n"
			f'{m[1]}    candidate = candidate.rstrip() + "\\n\\nThis script needs approval before it can run: " '
			f'+ ", ".join(_items) + "."\n'
			f"{m[1]}{m[2]}"
		),
	),
)

FINALIZE_EDITS = (
	(
		re.compile(r'^( *)if _vres\.get\("valid"\):\n', re.MULTILINE),
		lambda m: f"{m[1]}if not {SYNTAX_ONLY.format('_vres')}:\n",
	),
)


def execute():
	edit_script(REVIEW_SCRIPT, REVIEW_MARKER, REVIEW_EDITS)
	edit_script(FINALIZE_SCRIPT, FINALIZE_MARKER, FINALIZE_EDITS)


def edit_script(script_name: str, marker: str, edits: tuple) -> None:
	code = frappe.db.get_value("Server Script", script_name, "script")
	if not code or marker in code:
		return
	if any(len(pattern.findall(code)) != 1 for pattern, _new in edits):
		frappe.log_error(
			title="logix_review_passes_items_needing_approval: script anchor not found",
			message=f"{script_name} does not carry each anchor exactly once; it is left as it is.",
		)
		return
	for pattern, new in edits:
		code = pattern.sub(new, code, count=1)
	frappe.db.set_value("Server Script", script_name, "script", code, update_modified=False)
