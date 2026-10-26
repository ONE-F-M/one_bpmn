"""The agent_sandbox connector gets the run_tests and open_pull_request operations the agent maps call."""

import frappe

from one_bpmn.one_bpmn.connectors.seed import _import_operation

CONNECTOR = "agent_sandbox"
HANDLER = "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.dispatch_action"

_SHARED_FIELDS = [
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
		"help": "The branch this work started from - the exact same value on every call for one work order.",
	},
	{
		"name": "work_item_description",
		"label": "Work order",
		"type": "Text",
		"required": True,
		"help": "The work order in plain words, unchanged across every call - used to compute the same working branch each time.",
	},
]

OPERATIONS = [
	{
		"value": "run_tests",
		"label": "Run the test suite",
		"description": "Run the target app's real test suite against the current working branch and park until it answers.",
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
		},
		"fields": _SHARED_FIELDS,
	},
	{
		"value": "open_pull_request",
		"label": "Open the pull request",
		"description": (
			"Open (or update, on a retry) a pull request with every change made so far. "
			"Re-runs the real test suite itself first and marks the PR clearly if it fails."
		),
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
			"pr_url": "The opened pull request's URL, on a pass",
		},
		"fields": [
			*_SHARED_FIELDS,
			{
				"name": "summary",
				"label": "Summary",
				"type": "Text",
				"required": True,
				"help": "Plain-words summary of what changed, for the PR body.",
			},
		],
	},
]


def execute():
	if not frappe.db.exists("BPMN Connector", CONNECTOR):
		return
	for idx, operation in enumerate(OPERATIONS, start=1):
		_import_operation(CONNECTOR, operation, idx)
