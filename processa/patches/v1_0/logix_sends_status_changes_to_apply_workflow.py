"""Logix answers a status change with an Apply Workflow service task instead of a script that sets the state."""

import frappe

CLASSIFIER = (
	"Status changes, which override every rule above except DEBUG_EXISTING: a request to set, change, "
	'approve or complete a document\'s status or workflow state ("mark the overtime request as completed") '
	'is DISAMBIGUATE and next = "clarify". A script must not set a workflow state; an Apply Workflow '
	"service task on the map does it."
)
CLARIFIER = (
	"Status changes: when the request is to set, change, approve or complete a document's status, say that "
	"this is done by an Apply Workflow step on the map, not by a script, because that step saves and submits "
	"the document the way its workflow defines. Name the state they asked for. Offer options such as adding "
	"an Apply Workflow step to that state, or something else they meant."
)
WRITER = (
	"Status and approvals: never set workflow_state or docstatus in a script, through db_set, set_value or "
	"direct assignment. A status change belongs in an Apply Workflow service task on the map; say so and "
	"name the target state instead of writing it. Copying a state into another field or reading it is fine. "
	"Do not check roles in a script to decide who may perform a step: the user task's assignee and its task "
	"actions decide that, so point to them."
)
GUIDANCE = {
	"logix_intent_classifier": CLASSIFIER,
	"logix_clarifier": CLARIFIER,
	"logix_script_writer": WRITER,
	"logix_tool_writer": WRITER,
}


def execute():
	for agent_id, guidance in GUIDANCE.items():
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		if not name:
			continue
		config = frappe.get_doc("AI Agent Configuration", name)
		if guidance in (config.system_prompt or ""):
			continue
		config.system_prompt = ((config.system_prompt or "").rstrip() + "\n\n" + guidance).strip()
		config.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
