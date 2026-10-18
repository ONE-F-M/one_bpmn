"""The Orchestrator's brief says what an earlier attempt left on the Work Item's branch, so a retry continues from it."""

import frappe

SCRIPT = "Orchestrator Agent: Read the Work Item"
ANCHOR = 'result["work_item_brief"] = header + brief'
MARKER = "# Branch left by an earlier attempt"
BRANCH = """# Branch left by an earlier attempt, so a retry continues from its last commit.
from one_bpmn.one_bpmn.connectors.agent_criteria import branch_summary

branch_note = branch_summary(wi.name, wi.target_app, wi.git_branch)
if branch_note:
    brief += "\\n\\n" + branch_note
"""


def execute():
	if not frappe.db.exists("Server Script", SCRIPT):
		return
	script = frappe.db.get_value("Server Script", SCRIPT, "script") or ""
	if MARKER in script or ANCHOR not in script:
		return
	frappe.db.set_value("Server Script", SCRIPT, "script", script.replace(ANCHOR, BRANCH + ANCHOR, 1))
