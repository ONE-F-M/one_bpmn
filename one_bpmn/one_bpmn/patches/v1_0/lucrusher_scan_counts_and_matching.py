# Copyright (c) 2026, one-fm and contributors
"""LuCrusher's codebase scan reports real counts and matches on real words.

The scan tool, the snapshot Save Response stores and the context Build Context
renders each edit the BA site's copy of the script by anchored replace. The
system prompt gains the rule for answering where a number came from. Each edit
is applied only while its marker is absent; a script whose anchor moved is left
alone.
"""

import frappe

_AGENT_ID = "lucrusher_agent"
_SCAN_SCRIPT = "LuCrusher – Tool Scan Codebase"
_SAVE_SCRIPT = "LuCrusher – Save Response"
_CONTEXT_SCRIPT = "LuCrusher – Build Context"

SCAN_MARKER = "_GENERIC_WORDS = frozenset("
SAVE_MARKER = '"counts_line": _scan.get("counts_line")'
CONTEXT_MARKER = 'scan.get("counts_line")'

_GENERIC_WORDS = (
	"maintenance management settings setting item items type entry log list template "
	"request record detail details status master group rule config"
)

SCAN_EDITS = (
	(
		"    _SCORE_THRESHOLD = 0.30\n",
		"    _SCORE_THRESHOLD = 0.6\n"
		"    # Words that name a whole family of DocTypes weigh a quarter of any other word.\n"
		'    _GENERIC_WORDS = frozenset("' + _GENERIC_WORDS + '".split())\n'
		"    _GENERIC_WEIGHT = 0.25\n",
	),
	(
		"        intersection = kw_a & kw_b\n"
		"        if not intersection:\n"
		"            return 0.0\n"
		"        return len(intersection) / min(len(kw_a), len(kw_b))\n",
		"        intersection = kw_a & kw_b\n"
		"        if all(w in _GENERIC_WORDS for w in intersection):\n"
		"            return 0.0\n"
		"\n"
		"        def _weight(words):\n"
		"            return sum(_GENERIC_WEIGHT if w in _GENERIC_WORDS else 1.0 for w in words)\n"
		"\n"
		"        return _weight(intersection) / min(_weight(kw_a), _weight(kw_b))\n",
	),
	(
		'        fn_name = method.split(".")[-1] if method else ""\n'
		'        hook_kws = _extract_keywords(doctype + " " + str(hook.get("event") or "") + " " + fn_name)\n',
		'        if doctype == "*":\n'
		"            continue\n"
		'        fn_name = method.split(".")[-1] if method else ""\n'
		'        hook_kws = _extract_keywords(doctype + " " + fn_name)\n',
	),
	(
		'    matched_doctypes.sort(key=lambda x: x["score"], reverse=True)\n'
		"    matched_doctypes = matched_doctypes[:60]\n",
		'    matched_doctypes.sort(key=lambda x: x["score"], reverse=True)\n'
		"    _lcr_all_doctypes = matched_doctypes\n"
		"    matched_doctypes = matched_doctypes[:60]\n",
	),
	(
		'    matched_hooks.sort(key=lambda x: x["score"], reverse=True)\n'
		"    matched_hooks = matched_hooks[:120]\n",
		'    matched_hooks.sort(key=lambda x: x["score"], reverse=True)\n'
		"    _lcr_hooks_total = len(matched_hooks)\n"
		"    matched_hooks = matched_hooks[:120]\n",
	),
	(
		"    for dt in matched_doctypes[:30]:\n"
		'        if not dt["app"] or not dt.get("py_exists"):\n',
		"    for dt in _lcr_all_doctypes:\n"
		'        if not dt["app"] or not dt.get("py_exists"):\n',
	),
	(
		'    controller_classes.sort(key=lambda x: x["score"], reverse=True)\n',
		'    controller_classes.sort(key=lambda x: x["score"], reverse=True)\n'
		"    _lcr_controllers_total = len(controller_classes)\n"
		"    controller_classes = controller_classes[:30]\n",
	),
	(
		'    whitelisted_methods.sort(key=lambda x: x["score"], reverse=True)\n'
		"    whitelisted_methods = whitelisted_methods[:60]\n",
		'    whitelisted_methods.sort(key=lambda x: x["score"], reverse=True)\n'
		"    _lcr_methods_total = len(whitelisted_methods)\n"
		"    whitelisted_methods = whitelisted_methods[:60]\n",
	),
	(
		"    summary = _build_codebase_summary(\n        elements, matched_doctypes,",
		"    counts = {\n"
		'        "doctypes": len(_lcr_all_doctypes),\n'
		'        "hooks": _lcr_hooks_total,\n'
		'        "controllers": _lcr_controllers_total,\n'
		'        "whitelisted_methods": _lcr_methods_total,\n'
		"    }\n"
		"    shown = {\n"
		'        "doctypes": len(matched_doctypes),\n'
		'        "hooks": len(matched_hooks),\n'
		'        "controllers": len(controller_classes),\n'
		'        "whitelisted_methods": len(whitelisted_methods),\n'
		"    }\n"
		"    _lcr_parts = []\n"
		'    for _lcr_label, _lcr_key in (("DocTypes", "doctypes"), ("hooks", "hooks"),\n'
		'                                 ("controllers", "controllers"),\n'
		'                                 ("whitelisted methods", "whitelisted_methods")):\n'
		'        _lcr_parts.append(_lcr_label + " " + str(shown[_lcr_key]) + " of " + str(counts[_lcr_key]) + " shown")\n'
		'    counts_line = str(len(apps_scanned)) + " apps scanned; " + "; ".join(_lcr_parts)\n'
		"\n"
		"    summary = _build_codebase_summary(\n        elements, matched_doctypes,",
	),
	(
		'        lines.append("Analysed " + str(len(elements)) + " process element(s).")\n',
		'        lines.append("Analysed " + str(len(elements)) + " process element(s).")\n'
		"        lines.append(counts_line)\n",
	),
	(
		'        "summary": summary,\n        "apps_scanned": apps_scanned,\n        "error": None,',
		'        "summary": summary,\n        "apps_scanned": apps_scanned,\n'
		'        "counts": counts,\n        "shown": shown,\n        "counts_line": counts_line,\n'
		'        "error": None,',
	),
	(
		'        "counts": {\n            "doctypes": _count("matched_doctypes"),',
		'        "counts_line": scan.get("counts_line") or "",\n'
		'        "shown": scan.get("shown") or {},\n'
		'        "counts": scan.get("counts") or {\n            "doctypes": _count("matched_doctypes"),',
	),
)

SAVE_EDITS = (
	(
		'        "hooks_found": len(_hooks) if isinstance(_hooks, list) else int(_hooks or 0),\n    }',
		'        "hooks_found": len(_hooks) if isinstance(_hooks, list) else int(_hooks or 0),\n'
		'        "counts": _scan.get("counts"),\n'
		'        "counts_line": _scan.get("counts_line"),\n    }',
	),
)

_OLD_CONTEXT_LINE = (
	"        lines.append(\n"
	'            "  Codebase scan : " + str(n_apps) + " apps, " + str(n_dt)\n'
	'            + " DocTypes [ALREADY SCANNED — do not re-scan]"\n'
	"        )\n"
)

CONTEXT_EDITS = (
	(
		_OLD_CONTEXT_LINE,
		'        if scan.get("counts_line"):\n'
		"            lines.append(\n"
		'                "  Codebase scan : " + str(scan.get("counts_line"))\n'
		'                + " [scan tool result - ALREADY SCANNED, re-run only if the user asks]"\n'
		"            )\n"
		"        else:\n"
		+ "".join("    " + line + "\n" for line in _OLD_CONTEXT_LINE.splitlines()),
	),
)

SOURCES_HEADING = "## Sources of numbers"
SOURCES_BLOCK = (
	"Asked where a number or name in an earlier answer came from, quote the \"Codebase scan\" line "
	"of the migration context and say it is the scan tool result. If the context does not hold it, "
	"say you cannot see it and offer to re-run the scan. Never attribute a figure to another "
	"engagement or earlier session."
)

PROMPT_EDITS = (
	(
		"Do NOT re-run a tool the migration context above already reports as done.",
		"Do NOT re-run a tool the migration context above already reports as done, unless the user asks for a re-run.",
	),
	(
		"never re-run a tool it reports as done.",
		"never re-run a tool it reports as done unless the user asks for a re-run.",
	),
	(
		"app and DocType counts, the top 3 DocTypes",
		'the app count and the counts_line figures as written ("N of M shown"), the top 3 DocTypes',
	),
)


def apply_edits(text: str, edits: tuple, marker: str) -> tuple[str, bool]:
	"""Apply every edit or none: the marker blocks a repeat, a moved anchor blocks a partial edit."""
	if marker in text:
		return text, False
	if any(text.count(old) != 1 for old, _ in edits):
		return text, False
	for old, new in edits:
		text = text.replace(old, new, 1)
	return text, True


def with_sources_block(prompt: str) -> tuple[str, bool]:
	"""The system prompt with its re-run wording relaxed and the sources block appended once."""
	prompt = prompt or ""
	if SOURCES_HEADING in prompt:
		return prompt, False
	for old, new in PROMPT_EDITS:
		prompt = prompt.replace(old, new, 1)
	return f"{prompt.rstrip()}\n\n{SOURCES_HEADING}\n{SOURCES_BLOCK}\n", True


def _patch_script(name: str, edits: tuple, marker: str) -> None:
	if not frappe.db.exists("Server Script", name):
		return
	script = frappe.db.get_value("Server Script", name, "script") or ""
	updated, changed = apply_edits(script, edits, marker)
	if changed:
		frappe.db.set_value("Server Script", name, "script", updated, update_modified=False)
		print(f"lucrusher_scan_counts_and_matching: {name} updated")
	elif marker not in script:
		print(f"lucrusher_scan_counts_and_matching: {name} left alone, an anchor has moved")


def execute():
	_patch_script(_SCAN_SCRIPT, SCAN_EDITS, SCAN_MARKER)
	_patch_script(_SAVE_SCRIPT, SAVE_EDITS, SAVE_MARKER)
	_patch_script(_CONTEXT_SCRIPT, CONTEXT_EDITS, CONTEXT_MARKER)

	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _AGENT_ID}, "name")
	if name:
		prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
		updated, changed = with_sources_block(prompt)
		if changed:
			frappe.db.set_value("AI Agent Configuration", name, "system_prompt", updated, update_modified=False)
			print(f"lucrusher_scan_counts_and_matching: {name} told where numbers come from")
