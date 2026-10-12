"""The bug agents get the Report Not Reproducible tool, the Require Reproduction setting and their usage rules."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

from one_bpmn.one_bpmn.patches.v1_0.sandbox_tools_for_several_files_at_once import HEADER, NEEDS_BRIEF

TOOL = "Sandbox Tool: Report Not Reproducible"
HELD = ("Bug Agent", "Bug Programmer", "Bug Reviewer")
AGENTS = ("Bug Agent", "Bug Planner", "Bug Programmer", "Bug Reviewer")
MAX_TOOL_CALLS = 40
MODEL_RETRIES = 4

SCRIPT = (
	"""\
# Sandbox tool: report_not_reproducible. Shared verbatim by every sandbox agent, so nothing here may be agent-specific.
# Records that the bug could not be reproduced, with what was tried and what is needed, so a person gets the item.
from one_bpmn.one_bpmn.connectors.agent_reproduction import record_not_reproducible

"""
	+ HEADER
	+ f"""\
tried = task_data.get("tried")
needed = task_data.get("needed")

if not (target_app and git_branch and work_item_description):
    result["error"] = {NEEDS_BRIEF}
elif not str(tried or "").strip():
    result["error"] = "tried is required: what you did to reproduce the bug, and the files you read."
else:
    result.update(record_not_reproducible(target_app, git_branch, work_item_description, tried, needed, bpmn_id=bpmn_id, instance=instance))
"""
)

MARKER = "Working on a bug:"
READING = "- To read two or more files use read_files, and to find where something is used use grep_files.\n"
RULES = {
	"Bug Agent": MARKER + "\n"
	"- Submit a plan naming the suspected file and the test you will add before changing anything.\n"
	"- Write a test that fails because of the bug, and run_tests. Your change to the application is refused until that test fails for an application reason, not an import or syntax error and not another test.\n"
	"- After the fix, run_tests and see the same test pass before the pull request is opened. It is refused otherwise.\n"
	"- If you cannot make a test fail for the reported reason, call report_not_reproducible with what you tried and what is needed, make no changes, and start your final report with NOT REPRODUCIBLE. Do not retry.\n"
	+ READING + "- For a change in several places use apply_edits.\n",
	"Bug Planner": MARKER + "\n" + READING,
	"Bug Reviewer": MARKER + "\n" + READING
	+ "- The pull request is refused until the fix has been verified: run_tests after the last change must pass, including the test that reproduced the bug.\n",
}
RULES["Bug Programmer"] = RULES["Bug Agent"]


def marker() -> str:
	return MARKER


def execute():
	_tool()
	for name in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", name):
			continue
		doc = frappe.get_doc("AI Agent Configuration", name)
		prompt = with_block(doc.system_prompt, RULES[name])
		changed = prompt != doc.system_prompt
		doc.system_prompt = prompt
		if name in HELD and not doc.require_reproduction:
			doc.require_reproduction = 1
			changed = True
		if (doc.max_tool_calls or 0) < MAX_TOOL_CALLS:
			doc.max_tool_calls = MAX_TOOL_CALLS
			changed = True
		if (doc.max_retries or 0) < MODEL_RETRIES:
			doc.max_retries = MODEL_RETRIES
			changed = True
		if changed:
			doc.save(ignore_permissions=True)


def _tool():
	if frappe.db.exists("Server Script", TOOL):
		frappe.db.set_value("Server Script", TOOL, "script", SCRIPT)
		return
	frappe.get_doc(
		{"doctype": "Server Script", "name": TOOL, "script_type": "API", "allow_guest": 0, "disabled": 0, "script": SCRIPT}
	).insert(ignore_permissions=True)
