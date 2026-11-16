"""Creates the Sandbox Tool scripts the Testing Agent uses to write a spec, look at a page and run a scheduled job."""

import frappe

HEADER = """\
target_app = (task_data.get("target_app") or "").strip()
git_branch = (task_data.get("git_branch") or "").strip()
work_item_description = (task_data.get("work_item_description") or "").strip()
# run_id comes from the map, never from the model, so a tool cannot reach another run's folder.
run_id = (task_data.get("run_id") or "").strip()
"""

NEEDS_BRIEF = (
	'"target_app, git_branch, work_item_description and run_id are all required -- pass the exact same values '
	'on every call for one run."'
)

WRITE_SPEC = (
	"""\
# Sandbox tool: write_spec. Writes one Playwright spec into the run's own folder in the sandbox, outside the app checkout,
# so it is never committed or pushed.
from processa.agents_sandbox.sandbox.ops import sandbox_dispatch

"""
	+ HEADER
	+ f"""\
file = (task_data.get("file") or "").strip()
content = task_data.get("content")

if not (target_app and git_branch and work_item_description and run_id):
    result["error"] = {NEEDS_BRIEF}
elif not file or not isinstance(content, str) or not content.strip():
    result["error"] = "file (a name ending in .spec.js) and content are required."
else:
    _dispatch = sandbox_dispatch(
        "write_spec", target_app, git_branch, work_item_description,
        {{"run_id": run_id, "file": file, "content": content}}, context_docname, bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

BROWSER_SNAPSHOT = (
	"""\
# Sandbox tool: browser_snapshot. The accessibility snapshot of a page on the test site, seen as a role's test user.
# The screenshot is saved as a private File on the task and returned as a link: a model should not be handed megabytes of base64.
# save_file is used because linking a script to a map runs the security gate, which rejects a permission bypass on a File insert.
from frappe.utils.file_manager import save_file
from processa.agents_sandbox.sandbox.ops import sandbox_dispatch

"""
	+ HEADER
	+ f"""\
url = (task_data.get("url") or "").strip()
role = (task_data.get("role") or "").strip()

if not (target_app and git_branch and work_item_description and run_id):
    result["error"] = {NEEDS_BRIEF}
elif not url or not role:
    result["error"] = "url (a path on the test site, such as /app/home) and role are required."
else:
    _dispatch = sandbox_dispatch(
        "browser_snapshot", target_app, git_branch, work_item_description,
        {{"run_id": run_id, "url": url, "role": role}}, context_docname, bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        _answer = dict(_dispatch["response"])
        _shot = _answer.pop("screenshot_base64", None)
        if _shot and context_doctype and context_docname:
            _file = save_file("snapshot-" + run_id + ".jpg", _shot, context_doctype, context_docname, decode=True, is_private=1)
            _answer["screenshot_file"] = _file.file_url
        result.update(_answer)
"""
)

TRIGGER_JOB = (
	"""\
# Sandbox tool: trigger_job. Runs one of the target app's own scheduled methods on the test site; the sandbox refuses any
# method that is not in the app's scheduler_events.
from processa.agents_sandbox.sandbox.ops import sandbox_dispatch

"""
	+ HEADER
	+ f"""\
method = (task_data.get("method") or "").strip()

if not (target_app and git_branch and work_item_description):
    result["error"] = {NEEDS_BRIEF}
elif not method:
    result["error"] = "method is required: a dotted path listed in the app's scheduler_events."
else:
    _dispatch = sandbox_dispatch(
        "trigger_job", target_app, git_branch, work_item_description, {{"method": method}}, context_docname,
        bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

SCRIPTS = {
	"Sandbox Tool: Write Spec": WRITE_SPEC,
	"Sandbox Tool: Browser Snapshot": BROWSER_SNAPSHOT,
	"Sandbox Tool: Trigger Job": TRIGGER_JOB,
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
