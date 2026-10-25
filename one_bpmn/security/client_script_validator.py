"""Safety gates for the Form View and List View client scripts Docu writes.

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


MAX_SCRIPT_LENGTH = 8000

_LIST_FORBIDDEN = (
	(r"\beval\s*\(", "eval"),
	(r"(?-i:\bnew\s+Function\b|\bFunction\s*\()", "Function constructor"),
	(r"\bfetch\s*\(", "fetch"),
	(r"\bXMLHttpRequest\b", "XMLHttpRequest"),
	(r"\bWebSocket\b|\bsendBeacon\b", "network access"),
	(r"\bimportScripts\b|\bimport\s*\(", "dynamic import"),
	(r"document\s*\.\s*(cookie|write|domain)\b", "document.cookie/write/domain"),
	(r"\b(localStorage|sessionStorage)\b", "browser storage"),
	(r"<\s*script", "script tag"),
	(r"\bjavascript\s*:", "javascript: URL"),
	(r"https?://", "external URL"),
	(r"\bwindow\s*\.\s*(location|open)\b|\blocation\s*\.\s*(href|replace|assign)\b", "page redirect"),
)
_LIST_FORBIDDEN_RE = tuple((re.compile(p, re.IGNORECASE), label) for p, label in _LIST_FORBIDDEN)
_LIST_SETTINGS_ASSIGN = r"frappe\s*\.\s*listview_settings\s*\[\s*([\"'])(.+?)\1\s*\]\s*="


def validate_list_view_script(doctype: str, script: str) -> list[str]:
	"""Return the reasons a list script is unsafe or off-target; empty means acceptable."""
	script = (script or "").strip()
	if not script:
		return [_("The script is empty.")]
	if len(script) > MAX_SCRIPT_LENGTH:
		return [_("The script is longer than {0} characters.").format(MAX_SCRIPT_LENGTH)]

	problems = [
		_("It uses {0}, which a list script may not.").format(label)
		for rx, label in _LIST_FORBIDDEN_RE
		if rx.search(script)
	]
	targets = {m.group(2) for m in re.finditer(_LIST_SETTINGS_ASSIGN, script)}
	if not targets:
		problems.append(_("It must set frappe.listview_settings for {0}.").format(doctype))
	elif targets != {doctype}:
		problems.append(_("It may only change the list of {0}.").format(doctype))
	return problems
