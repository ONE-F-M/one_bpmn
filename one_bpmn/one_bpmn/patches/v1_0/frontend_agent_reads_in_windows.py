"""A long file is read in windows, search hits say which window to read, and the catalogue stops carrying the tailwind config.

read_file with no limit returns up to 400 lines, fewer when they would not fit the tool result cap, with a
hint to call again with offset and limit; path, total_lines, line_range and hint come before content so a
cut result still carries them. search_frontend hits carry an offset and limit. component_catalogue points at
the tailwind config, which becomes a resource of the frontend-house-style skill. Idempotent.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

READ_FILE = "Sandbox Tool: Read File"
SEARCH_FRONTEND = "Frontend Agent: Tool Search Frontend"
COMPONENT_CATALOGUE = "Frontend Agent: Tool Component Catalogue"
SKILL = "frontend-house-style"
TAILWIND_RESOURCE = "tailwind-config"

READ_IMPORT = (
	"from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import sandbox_dispatch, read_budget_exceeded\n"
)
READ_SETTINGS = (
	"import json\n"
	+ READ_IMPORT
	+ "\n# A read with no limit returns at most this many lines, fewer when they would not fit the tool result cap.\n"
	+ "_WINDOW_LINES = 400\n"
	+ "_WINDOW_CHARS = 19000\n"
)

READ_LINES = """            _lines = _content.split("\\n")
            result["path"] = path
            result["total_lines"] = len(_lines)
"""
READ_DEFAULT_WINDOW = (
	READ_LINES
	+ """            _default_window = not (offset or limit) and len(_lines) > _WINDOW_LINES
            if _default_window:
                offset = 1
                _room = _WINDOW_CHARS
                for _l in _lines[:_WINDOW_LINES]:
                    _room -= len(json.dumps(_l))
                    if _room < 0:
                        break
                    limit += 1
                limit = limit or 1
"""
)

READ_RANGE = """                result["line_range"] = str(_from) + "-" + str(_to) + " of " + str(len(_lines))
"""
READ_HINT = (
	READ_RANGE
	+ """                if _default_window:
                    result["hint"] = (
                        path + " has " + str(len(_lines)) + " lines; these are lines " + str(_from) + "-" + str(_to)
                        + ". Call read_file again with offset and limit for the part you need, for example offset="
                        + str(_to + 1) + " limit=" + str(_WINDOW_LINES) + "."
                    )
"""
)

READ_LAST = """                    result["unchanged_since_earlier_read"] = True
"""
READ_KEY_ORDER = (
	READ_LAST
	+ """
# Which file and which lines come first, so a result cut at the tool cap still carries them.
_front = {}
for _k in ("path", "total_lines", "line_range", "hint"):
    if _k in result:
        _front[_k] = result.pop(_k)
_rest = dict(result)
result.clear()
result.update(_front)
result.update(_rest)
"""
)

SEARCH_HIT = """                _hits.append({"path": _p, "line": _n, "text": _line.strip()[:220]})
"""
SEARCH_HIT_WINDOW = """                _hits.append({"path": _p, "line": _n, "text": _line.strip()[:220], "offset": max(1, _n - 20), "limit": 60})
"""

CATALOGUE_TAILWIND = """_tw = fs.read_text("one_bpmn/spiff/tailwind.config.cjs")
result["tailwind_config"] = (_tw.get("content") or "")[:6000] if _tw.get("ok") else ""
"""
CATALOGUE_POINTER = """result["tailwind_config"] = (
    "Not included here. Load it with load_skill_resource('frontend-house-style', 'tailwind-config')."
)
"""


def execute():
	_edit_named(
		READ_FILE,
		[
			(READ_IMPORT, READ_SETTINGS),
			(READ_LINES, READ_DEFAULT_WINDOW),
			(READ_RANGE, READ_HINT),
			(READ_LAST, READ_KEY_ORDER),
		],
	)
	_edit_named(SEARCH_FRONTEND, [(SEARCH_HIT, SEARCH_HIT_WINDOW)])
	if _add_tailwind_resource():
		_edit_named(COMPONENT_CATALOGUE, [(CATALOGUE_TAILWIND, CATALOGUE_POINTER)])


def _edit_named(name: str, edits: list):
	"""Apply each (anchor, replacement) to the named Server Script; log and leave it as-is if any anchor is missing."""
	if not frappe.db.exists("Server Script", name):
		return
	doc = frappe.get_doc("Server Script", name)
	script = doc.script or ""
	for anchor, replacement in edits:
		edited = apply_edit(script, anchor, replacement)
		if edited is None:
			frappe.log_error(
				title="frontend_agent_reads_in_windows: anchor not found",
				message=f"{name} has no single '{anchor.strip()[:80]}' line; the script is left as-is.",
			)
			return
		script = edited
	if script != doc.script:
		doc.script = script
		doc.save(ignore_permissions=True)


def _add_tailwind_resource() -> bool:
	"""Copy the bench's tailwind config into the skill; False when the skill or the file is missing."""
	if not frappe.db.exists("AI Skill", SKILL):
		return False
	path = frappe.get_app_source_path("one_bpmn", "spiff", "tailwind.config.cjs")
	try:
		with open(path) as handle:
			config = handle.read()
	except FileNotFoundError:
		return False
	skill = frappe.get_doc("AI Skill", SKILL)
	row = next((r for r in skill.resources if r.resource_name == TAILWIND_RESOURCE), None)
	if row is None:
		skill.append(
			"resources",
			{"resource_type": "Reference", "resource_name": TAILWIND_RESOURCE, "resource_value": config},
		)
	elif row.resource_value != config:
		row.resource_value = config
	skill.save(ignore_permissions=True)
	return True
