"""Fills action, work_item and agent_name on existing Agent Sandbox Run rows from their request payload."""

import frappe

from one_bpmn.one_bpmn.doctype.agent_sandbox_run.agent_sandbox_run import identity_from_payload


def execute():
	rows = frappe.get_all(
		"Agent Sandbox Run",
		filters={"action": ["is", "not set"], "request_payload": ["is", "set"]},
		fields=["name", "request_payload"],
	)
	for row in rows:
		identity = identity_from_payload(row.request_payload)
		if identity:
			frappe.db.set_value("Agent Sandbox Run", row.name, identity, update_modified=False)
