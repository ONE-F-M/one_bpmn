# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Adds run_tests and open_pull_request as real operations on the existing
agent_sandbox connector, alongside dispatch — same additive re-seed pattern
seed_agent_sandbox_connector.py's own #26-08-2026-v2 re-run used ("adds
files alongside work_item_description").

These two, together with the 4 Server-Script-backed tools (Sandbox Tool:
Read/Write/Edit/List File), are what let each of the 6 sandbox actions be
its own real, directly-callable BPMN tool — read_file/write_file/edit_file/
list_files/run_tests/open_pull_request all live as shapes inside the Dev
Agent's own dev_agent_tools ad-hoc sub-process now, matching how the
Orchestrator Agent's own tools (wi_comment, delegate_dev_agent, etc.) are
real Script/Service Tasks, not schema-only declarations. run_tests and
open_pull_request are minutes-scale (they may re-run the real test suite),
so — unlike the fast file-op tools, which answer inline — they still park
the calling step exactly like dispatch() always has (see
agent_sandbox_ops.py::_dispatch_single_action).
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

DEV_AGENT_SANDBOX_CONNECTOR_ADDITIONS = {
	"connectorId": "agent_sandbox",
	"label": "Dev Agent Sandbox",
	"description": (
		"Dispatch a development work order to the isolated Cloud Run sandbox: clone "
		"the target app, run its real test suite, and — only on a pass — deliver the "
		"change as a pull request."
	),
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
			"handlerPath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.dispatch",
			"fields": [
				{
					"name": "target_app", "label": "Target app", "type": "Dropdown", "required": True,
					"choicesSourcePath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.target_app_choices",
					"help": "Which installed app's working tree the sandbox clones and tests.",
				},
				{
					"name": "git_branch", "label": "Branch", "type": "String", "required": True, "expression": True,
					"help": "Branch to start the work from. Jinja is allowed, e.g. {{ doc.branch }}.",
				},
				{
					"name": "work_item_description", "label": "Work order", "type": "Text", "required": True,
					"expression": True,
					"help": "The development task in plain words, for the PR title/body. Jinja is allowed, e.g. {{ doc.description }}.",
				},
				{
					"name": "files", "label": "Files", "type": "Text", "required": True, "expression": True,
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
				"run": "The Agent Sandbox Run record tracking this dispatch",
				"state": "Final state: completed or failed",
				"pr_url": "The opened pull request's URL, on a pass",
			},
		},
		{
			"value": "run_tests",
			"label": "Run the test suite",
			"description": "Run the target app's real test suite against the current working branch and park until it answers.",
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.run_tests",
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
			"handlerPath": "one_bpmn.one_bpmn.connectors.agent_sandbox_ops.open_pull_request",
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
	state = import_manifest(DEV_AGENT_SANDBOX_CONNECTOR_ADDITIONS, overwrite=True)
	print(f"agent_sandbox connector {state}")

	operations = frappe.get_all(
		"BPMN Connector Operation", filters={"connector": "agent_sandbox"}, pluck="operation_id"
	)
	missing = {"dispatch", "run_tests", "open_pull_request"} - set(operations)
	if missing:
		frappe.throw(f"agent_sandbox connector is missing expected operation(s): {', '.join(sorted(missing))}")
	print(f"  operations: {', '.join(operations)}")
	frappe.clear_cache()
