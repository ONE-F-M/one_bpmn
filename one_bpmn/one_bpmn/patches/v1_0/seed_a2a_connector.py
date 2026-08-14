# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001933: the generic ``a2a`` connector.

ONE connector serves every remote agent — which one is a parameter,
resolved through the A2A Remote Agent registry, so adding a partner is a
registry row and never a new connector. There is no base URL or
credential here for the same reason: both live on the registry entry
whose endpoint is being called.

Goes in through the ordinary import path, and never overwrites: a site
sets its own allowed_roles on the connector row.
"""

import frappe

from one_bpmn.one_bpmn.connectors.seed import import_manifest

A2A_CONNECTOR = {
	"connectorId": "a2a",
	"label": "A2A Remote Agent",
	"description": "Delegate a task to an approved remote agent over the A2A protocol.",
	"icon": {
		"path": "M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
		"color": "#7c3aed",
		"label": "A2A",
	},
	"execution": {"type": "Python Handler"},
	"operations": [
		{
			"operationId": "delegate_task",
			"label": "Delegate task to remote agent",
			"description": (
				"Send a task to an approved remote A2A agent. A fast reply comes back "
				"inline; anything slower parks this step until the answer arrives."
			),
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.a2a_client_ops.delegate_task",
			"fields": [
				{
					"name": "remote_agent",
					"label": "Remote agent",
					"type": "Dropdown",
					"required": True,
					"choicesSourcePath": "one_bpmn.one_bpmn.connectors.a2a_client_ops.remote_agent_choices",
					"help": "Only enabled, approved registry entries appear here.",
				},
				{
					"name": "instruction",
					"label": "Instruction",
					"type": "Text",
					"required": True,
					"help": "What the remote agent should do. Jinja is allowed, e.g. {{ doc.subject }}.",
				},
				{
					"name": "delegating_agent",
					"label": "Delegating agent",
					"type": "String",
					"help": (
						"Whose sub-agent list and delegation limits apply. Leave blank on an "
						"agent's own map — the agent is derived from it."
					),
				},
				{
					"name": "parent_task",
					"label": "Parent A2A task",
					"type": "String",
					"help": "Continues an existing delegation chain; blank starts a new one.",
				},
				{
					"name": "timeout_minutes",
					"label": "Deadline (minutes)",
					"type": "String",
					"help": "Overrides the registry entry's deadline for this step only.",
				},
				{
					"name": "input_assignee",
					"label": "Answer questions as",
					"type": "String",
					"help": "Who is asked when the remote agent needs clarification.",
				},
				{
					"name": "input_role",
					"label": "Answer questions role",
					"type": "String",
					"help": "Role assigned when no specific user is named.",
				},
			],
			"output": {
				"a2a_task": "The A2A Task record tracking this delegation",
				"state": "Final state: completed, failed, canceled or timed-out",
				"text": "The remote agent's reply text",
			},
		}
	],
}


def execute():
	state = import_manifest(A2A_CONNECTOR)
	if state == "skipped":
		print("a2a connector already present, left as configured")
	else:
		print(f"a2a connector {state}")
	frappe.clear_cache()
