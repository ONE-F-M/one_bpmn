"""Creates the Sandbox Tool script an agent uses to report, per acceptance criterion, what it did and where."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.sandbox_tools_for_several_files_at_once import HEADER, NEEDS_BRIEF

NAME = "Sandbox Tool: Submit Evidence"

SCRIPT = (
	"""\
# Sandbox tool: submit_evidence. Shared verbatim by every sandbox agent, so nothing here may be agent-specific.
# Records one row per acceptance criterion (id, status, evidence) and checks the evidence against the branch's diff.
from one_bpmn.one_bpmn.connectors.agent_criteria import record_evidence

"""
	+ HEADER
	+ f"""\
evidence = task_data.get("evidence")

if not (target_app and git_branch and work_item_description):
    result["error"] = {NEEDS_BRIEF}
elif not isinstance(evidence, list) or not evidence:
    result["error"] = "evidence is required: a list with one {{id, status, evidence}} row per acceptance criterion."
else:
    result.update(record_evidence(target_app, git_branch, work_item_description, evidence, bpmn_id=bpmn_id, instance=instance))
"""
)


def execute():
	if frappe.db.exists("Server Script", NAME):
		frappe.db.set_value("Server Script", NAME, "script", SCRIPT)
		return
	frappe.get_doc(
		{"doctype": "Server Script", "name": NAME, "script_type": "API", "allow_guest": 0, "disabled": 0, "script": SCRIPT}
	).insert(ignore_permissions=True)
