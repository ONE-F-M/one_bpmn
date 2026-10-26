"""Creates the Sandbox Tool scripts that read, search and edit several files in one call."""

import frappe

HEADER = """\
target_app = (task_data.get("target_app") or "").strip()
git_branch = (task_data.get("git_branch") or "").strip()
work_item_description = (task_data.get("work_item_description") or "").strip()
"""

NEEDS_BRIEF = (
	'"target_app, git_branch, and work_item_description are all required -- pass the exact same values '
	'on every call for one work order."'
)

READ_FILES = (
	"""\
# Sandbox tool: read_files. Shared verbatim by every sandbox agent, so nothing here may be agent-specific.
# Reads up to 10 files in one call. Counts as one read against the run's read budget.
from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import sandbox_dispatch, read_budget_exceeded

"""
	+ HEADER
	+ f"""\
paths = task_data.get("paths")

_budget_error = read_budget_exceeded(instance)

if not (target_app and git_branch and work_item_description):
    result["error"] = {NEEDS_BRIEF}
elif not isinstance(paths, list) or not paths:
    result["error"] = "paths is required: a list of repo-relative file paths, at most 10."
elif _budget_error:
    result["error"] = _budget_error
else:
    _dispatch = sandbox_dispatch(
        "read_files", target_app, git_branch, work_item_description, {{"paths": paths}}, context_docname, bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

GREP_FILES = (
	"""\
# Sandbox tool: grep_files. Shared verbatim by every sandbox agent, so nothing here may be agent-specific.
# Finds lines matching a pattern, optionally under a path prefix. Counts as one read against the run's read budget.
from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import sandbox_dispatch, read_budget_exceeded

"""
	+ HEADER
	+ f"""\
pattern = task_data.get("pattern")
path_prefix = (task_data.get("path_prefix") or "").strip()
literal = bool(task_data.get("literal"))

_budget_error = read_budget_exceeded(instance)

if not (target_app and git_branch and work_item_description):
    result["error"] = {NEEDS_BRIEF}
elif not isinstance(pattern, str) or not pattern.strip():
    result["error"] = "pattern is required."
elif _budget_error:
    result["error"] = _budget_error
else:
    _dispatch = sandbox_dispatch(
        "grep_files", target_app, git_branch, work_item_description,
        {{"pattern": pattern, "path_prefix": path_prefix, "literal": literal}}, context_docname, bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

APPLY_EDITS = (
	"""\
# Sandbox tool: apply_edits. Shared verbatim by every sandbox agent, so nothing here may be agent-specific.
# Applies up to 20 edit_file replacements in order, committed together. Stops at the first one that fails.
from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import sandbox_dispatch

"""
	+ HEADER
	+ f"""\
edits = task_data.get("edits")

if not (target_app and git_branch and work_item_description):
    result["error"] = {NEEDS_BRIEF}
elif not isinstance(edits, list) or not edits:
    result["error"] = "edits is required: a list of {{path, old_string, new_string}}, at most 20."
else:
    _dispatch = sandbox_dispatch(
        "apply_edits", target_app, git_branch, work_item_description, {{"edits": edits}}, context_docname, bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

SCRIPTS = {
	"Sandbox Tool: Read Files": READ_FILES,
	"Sandbox Tool: Grep Files": GREP_FILES,
	"Sandbox Tool: Apply Edits": APPLY_EDITS,
}


def execute():
	for name, script in SCRIPTS.items():
		if frappe.db.exists("Server Script", name):
			frappe.db.set_value("Server Script", name, "script", script)
			continue
		frappe.get_doc({
			"doctype": "Server Script", "name": name, "script_type": "API",
			"allow_guest": 0, "disabled": 0, "script": script,
		}).insert(ignore_permissions=True)
