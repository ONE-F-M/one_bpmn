"""Safety gate for the List View Client Scripts Docu writes.

A Client Script runs in every user's browser, so apply_list_view_script re-runs this server-side and
refuses on any violation. The model's output and the client payload are never trusted.
"""

from __future__ import annotations

import re

from frappe import _

MAX_SCRIPT_LENGTH = 8000

_FORBIDDEN = (
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
_FORBIDDEN_RE = tuple((re.compile(p, re.IGNORECASE), label) for p, label in _FORBIDDEN)
_SETTINGS_ASSIGN = r"frappe\s*\.\s*listview_settings\s*\[\s*([\"'])(.+?)\1\s*\]\s*="


def validate_list_view_script(doctype: str, script: str) -> list[str]:
	"""Return the reasons a list script is unsafe or off-target; empty means acceptable."""
	script = (script or "").strip()
	if not script:
		return [_("The script is empty.")]
	if len(script) > MAX_SCRIPT_LENGTH:
		return [_("The script is longer than {0} characters.").format(MAX_SCRIPT_LENGTH)]

	problems = [_("It uses {0}, which a list script may not.").format(label) for rx, label in _FORBIDDEN_RE if rx.search(script)]
	targets = {m.group(2) for m in re.finditer(_SETTINGS_ASSIGN, script)}
	if not targets:
		problems.append(_("It must set frappe.listview_settings for {0}.").format(doctype))
	elif targets != {doctype}:
		problems.append(_("It may only change the list of {0}.").format(doctype))
	return problems
