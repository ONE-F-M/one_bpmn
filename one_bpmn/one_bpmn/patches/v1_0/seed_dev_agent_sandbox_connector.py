# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The ``dev_agent_sandbox`` connector — dispatches development work to the
external Cloud Run sandbox (the AI Dev Agent feature).

No base URL or credential on the connector row: both are resolved inside
the handler from Processa Settings (Sandbox URL, and a freshly minted Cloud
Run identity token — never a static secret a declarative HTTP Request
operation could carry). Mirrors seed_a2a_connector.py's shape for the same
reason that one has none either — the real target/auth lives elsewhere.
"""

import frappe

from one_bpmn.one_bpmn.connectors.seed import import_manifest

DEV_AGENT_SANDBOX_CONNECTOR = {
	"connectorId": "dev_agent_sandbox",
	"label": "Dev Agent Sandbox",
	"description": (
		"Dispatch a development work order to the isolated Cloud Run sandbox: clone "
		"the target app, run its real test suite, and — only on a pass — deliver the "
		"change as a pull request."
	),
	# Placeholder geometry (a simple wrench-like mark) — swap for a proper
	# lucide icon path in the desk UI; this only affects the canvas icon.
	"icon": {
		"path": "M14 3l3 3l-8 8l-3 -3z M4 20l4 -1l9 -9l-3 -3l-9 9z",
		"color": "#f97316",
		"label": "Dev Agent",
		"stroke": True,
	},
	"execution": {"type": "Python Handler"},
	"operations": [
		{
			"value": "dispatch",
			"label": "Dispatch to sandbox",
			"description": (
				"Clone the target app into a disposable sandbox, run its real test suite, "
				"and park this step until the sandbox answers or times out."
			),
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.dev_agent_sandbox_ops.dispatch",
			"fields": [
				{
					"name": "target_app",
					"label": "Target app",
					"type": "Dropdown",
					"required": True,
					"choicesSourcePath": "one_bpmn.one_bpmn.connectors.dev_agent_sandbox_ops.target_app_choices",
					"help": "Which installed app's working tree the sandbox clones and tests.",
				},
				{
					"name": "git_branch",
					"label": "Branch",
					"type": "String",
					"required": True,
					"expression": True,
					"help": "Branch to start the work from. Jinja is allowed, e.g. {{ doc.branch }}.",
				},
				{
					"name": "work_item_description",
					"label": "Work order",
					"type": "Text",
					"required": True,
					"expression": True,
					"help": "The development task in plain words, for the PR title/body. Jinja is allowed, e.g. {{ doc.description }}.",
				},
				{
					"name": "files",
					"label": "Files",
					"type": "Text",
					"required": True,
					"expression": True,
					"help": (
						"The exact {path: new content} plan to apply, as a JSON object — the sandbox "
						"writes these files verbatim and tests, it does not decide what to change. "
						"Always supplied by the AI tool call; this manifest field only documents it "
						"for the modeler UI, since the actual value is read from task data, not "
						"rendered through this field's Jinja expression."
					),
				},
			],
			"output": {
				"run": "The Dev Agent Sandbox Run record tracking this dispatch",
				"state": "Final state: completed or failed",
				"pr_url": "The opened pull request's URL, on a pass",
			},
		}
	],
}


def execute():
	# overwrite=True: the connector carries no site-owned settings (no base
	# URL, no credential — those come from Processa Settings and a service
	# account key), so re-applying cannot undo local configuration.
	state = import_manifest(DEV_AGENT_SANDBOX_CONNECTOR, overwrite=True)
	print(f"dev_agent_sandbox connector {state}")

	operations = frappe.get_all(
		"BPMN Connector Operation", filters={"connector": "dev_agent_sandbox"}, pluck="operation_id"
	)
	if not operations:
		frappe.throw(
			"The dev_agent_sandbox connector seeded with no operations — the modeler would show it as unusable."
		)
	print(f"  operations: {', '.join(operations)}")
	frappe.clear_cache()
