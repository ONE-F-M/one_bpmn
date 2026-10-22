"""Safety gate for Form View client scripts Docu writes.

A client script runs in every user's browser, so the apply endpoint re-runs this
server-side and refuses on any violation; a script posted by the client is never trusted.
"""

import re

import frappe
from frappe import _

MAX_SCRIPT_CHARS = 20000

# pattern -> what to tell the person
FORBIDDEN = {
	r"\beval\s*\(": "eval",
	r"\bnew\s+Function\b": "new Function",
	r"\bfetch\s*\(": "fetch (use frappe.call)",
	r"\bXMLHttpRequest\b": "XMLHttpRequest (use frappe.call)",
	r"\bdocument\.cookie\b": "document.cookie",
	r"\b(?:localStorage|sessionStorage)\b": "browser storage",
	r"\bcur_frm\b": "cur_frm (use the frm argument)",
	r"\bconsole\.(?:log|debug)\b": "console.log",
	r"\bdebugger\b": "debugger",
	r"<script\b": "a script tag",
}

FIELD_ARG_CALLS = re.compile(
	r"\bfrm\.(?:set_value|toggle_display|toggle_reqd|toggle_enable|set_df_property|set_query)\(\s*\"([^\"]+)\""
)


def validate_form_script(doctype: str, script: str) -> list:
	"""Return the plain-English problems with a Form View script; empty means it may be saved."""
	script = script or ""
	if not script.strip():
		return [_("The script is empty.")]
	if len(script) > MAX_SCRIPT_CHARS:
		return [_("The script is longer than {0} characters.").format(MAX_SCRIPT_CHARS)]

	problems = [
		_("The script uses {0}, which Docu does not write.").format(label)
		for pattern, label in FORBIDDEN.items()
		if re.search(pattern, script)
	]
	if f'frappe.ui.form.on("{doctype}"' not in script:
		problems.append(_('The script must start from frappe.ui.form.on("{0}", ...).').format(doctype))

	meta = frappe.get_meta(doctype)
	for fieldname in dict.fromkeys(FIELD_ARG_CALLS.findall(script)):
		if not meta.get_field(fieldname):
			problems.append(_("{0} has no field named {1}.").format(doctype, fieldname))
	return problems
