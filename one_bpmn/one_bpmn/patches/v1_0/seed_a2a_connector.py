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
	"label": "Agent to Agent (A2A)",
	"description": (
		"Hand a task to another agent — one on this site, or an approved remote agent "
		"over the A2A protocol."
	),
	# Two arrows passing each other (lucide arrow-right-left): work goes over,
	# an answer comes back. The stacked-layers mark this replaced said nothing
	# about an exchange — it read as "a pile of things".
	"icon": {
		"path": "m16 3l4 4l-4 4m4-4H4m4 14l-4-4l4-4m-4 4h16",
		# violet-500, to sit at the same weight as the other service icons
		# (indigo-500, sky-500, amber-500, green-500, teal-500). The 600 shade
		# it used before read as heavier and darker than everything around it.
		"color": "#8b5cf6",
		"label": "A2A",
		"stroke": True,
	},
	"execution": {"type": "Python Handler"},
	"operations": [
		{
			# The primary case: both agents live in this bench, so there is no
			# trust boundary to cross — no registry entry, no approved client,
			# no HTTP, and the target needs no exposure flag. Only the
			# delegating agent's allowed-delegates list and its guardrails
			# apply, because those are about scope and loops.
			"value": "delegate_to_local_agent",
			"label": "Delegate task to an agent on this site",
			"description": (
				"Hand a task to another agent in this bench. A fast agent answers inline; "
				"a slower one parks this step until it finishes or asks a question."
			),
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.a2a_client_ops.delegate_to_local_agent",
			"fields": [
				{
					"name": "agent",
					"label": "Agent",
					"type": "Dropdown",
					"required": True,
					"choicesSourcePath": "one_bpmn.one_bpmn.connectors.a2a_client_ops.local_agent_choices",
					"help": "Any live agent on this site. It does not need to be exposed over A2A.",
				},
				{
					"name": "instruction",
					"label": "Instruction",
					"type": "Text",
					"required": True,
					"help": "What the agent should do. Jinja is allowed, e.g. {{ doc.subject }}.",
				},
				{
					"name": "timeout_minutes",
					"label": "Deadline override (minutes)",
					"type": "String",
					"help": (
						"Usually leave blank: the deadline comes from the agent you are "
						"delegating to. Set this only to override it for this step."
					),
				},
			],
			"output": {
				"a2a_task": "The A2A Task record tracking this delegation",
				"state": "Final state: completed, failed, canceled or timed-out",
				"text": "The agent's reply text",
			},
		},
		{
			# The importer reads an operation's id from "value" (see
			# connectors/seed.py::_import_operation) — an "operationId" key is
			# silently skipped, which leaves a connector with no operations.
			"value": "delegate_task",
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
	# overwrite=True on purpose: the connector carries no site-owned settings
	# (no base URL, no credential — those live on each A2A Remote Agent row),
	# so re-applying cannot undo local configuration, and it repairs a row
	# seeded before the operation-key fix. allowed_roles is a child table the
	# import does not touch.
	state = import_manifest(A2A_CONNECTOR, overwrite=True)
	print(f"a2a connector {state}")

	operations = frappe.get_all(
		"BPMN Connector Operation", filters={"connector": "a2a"}, pluck="operation_id"
	)
	if not operations:
		frappe.throw(
			"The a2a connector seeded with no operations — the modeler would show it as unusable."
		)
	print(f"  operations: {', '.join(operations)}")
	frappe.clear_cache()
