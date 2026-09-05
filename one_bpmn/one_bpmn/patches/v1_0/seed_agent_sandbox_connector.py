# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The ``agent_sandbox`` connector — dispatches development work to the
external Cloud Run sandbox (the AI Dev Agent feature).

No base URL or credential on the connector row: both are resolved inside
each handler from Processa Settings (Sandbox URL, and a freshly minted
Cloud Run identity token — never a static secret a declarative HTTP Request
operation could carry). Mirrors seed_a2a_connector.py's shape for the same
reason that one has none either — the real target/auth lives elsewhere.

Originally seeded a single "dispatch" operation (one bundled work-order call
whose own internal coding loop decided what to read/write/test/PR). That
operation is retired (#04-09-2026-v3) now that each action is its own real,
independently-dispatched BPMN tool: run_tests and open_pull_request are the
two operations below (minutes-scale, so they park the calling step and wait
for an async callback — see agent_sandbox_ops.py::_dispatch_single_action);
the four fast file-op tools (read_file/write_file/edit_file/list_files) call
sandbox_dispatch() directly from their own Server Scripts and were never
operations on this connector.

Both operations below share one handlerPath (#04-09-2026-v4,
agent_sandbox_ops.dispatch_action) rather than each naming its own Python
function — the handler reads which operation it was configured as off ctx
at dispatch time. This is deliberate: it means a future third slow sandbox
action needs only a new BPMN Connector Operation record naming this same
handlerPath (creatable from the desk UI, no patch, no new Python), as long
as the sandbox itself already knows what to do with that action name.
"""

import frappe

from one_bpmn.one_bpmn.connectors.seed import import_manifest

_COMMON_FIELDS = [
	{
		"name": "target_app",
		"label": "Target app",
		"type": "Dropdown",
		"required": True,
		"choicesSourcePath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.target_app_choices",
		"help": "Which installed app's working tree this action operates on. Must match the same app used across every call for this work order.",
	},
	{
		"name": "git_branch",
		"label": "Branch",
		"type": "String",
		"required": True,
		"expression": True,
		"help": "The branch this work started from — the exact same value on every call for one work order.",
	},
	{
		"name": "work_item_description",
		"label": "Work order",
		"type": "Text",
		"required": True,
		"expression": True,
		"help": "The work order in plain words, unchanged across every call — used to compute the same working branch each time.",
	},
]

DEV_AGENT_SANDBOX_CONNECTOR = {
	"connectorId": "agent_sandbox",
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
			"value": "run_tests",
			"label": "Run the test suite",
			"description": "Run the target app's real test suite against the current working branch and park until it answers.",
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.dispatch_action",
			"fields": list(_COMMON_FIELDS),
			"output": {
				"run": "The Agent Sandbox Run record tracking this dispatch",
				"state": "Final state: completed or failed",
			},
		},
		{
			"value": "open_pull_request",
			"label": "Open the pull request",
			"description": (
				"Open (or update, on a retry) a pull request with every change made so far. "
				"Re-runs the real test suite itself first and marks the PR clearly if it fails."
			),
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.dispatch_action",
			"fields": [
				*_COMMON_FIELDS,
				{
					"name": "summary", "label": "Summary", "type": "Text", "required": True, "expression": True,
					"help": "Plain-words summary of what changed, for the PR body.",
				},
			],
			"output": {
				"run": "The Agent Sandbox Run record tracking this dispatch",
				"state": "Final state: completed or failed",
				"pr_url": "The opened pull request's URL, on a pass",
			},
		},
	],
}


def execute():
	# overwrite=True: the connector carries no site-owned settings (no base
	# URL, no credential — those come from Processa Settings and a service
	# account key), so re-applying cannot undo local configuration. It also
	# means a stale operation no longer in the manifest (like the retired
	# "dispatch") is deleted on re-run, not just left behind — see
	# import_manifest's own keep-set logic.
	state = import_manifest(DEV_AGENT_SANDBOX_CONNECTOR, overwrite=True)
	print(f"agent_sandbox connector {state}")

	operations = frappe.get_all(
		"BPMN Connector Operation", filters={"connector": "agent_sandbox"}, pluck="operation_id"
	)
	missing = {"run_tests", "open_pull_request"} - set(operations)
	if missing:
		frappe.throw(f"agent_sandbox connector is missing expected operation(s): {', '.join(sorted(missing))}")
	print(f"  operations: {', '.join(operations)}")
	frappe.clear_cache()
