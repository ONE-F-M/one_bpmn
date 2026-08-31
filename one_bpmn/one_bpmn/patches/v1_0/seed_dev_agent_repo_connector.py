# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The ``dev_agent_repo`` connector — read-only GitHub access Dev Agent's
own planning step uses to see a target app's actual source before proposing
file changes. Mirrors seed_dev_agent_sandbox_connector.py's shape: no base
URL or credential on the connector row, both resolved inside the handler
from Processa Settings.
"""

import frappe

from one_bpmn.one_bpmn.connectors.seed import import_manifest

DEV_AGENT_REPO_CONNECTOR = {
	"connectorId": "dev_agent_repo",
	"label": "Dev Agent Repo",
	"description": (
		"Read-only GitHub access to a target app's source at a given branch — "
		"lets a planning agent see what it is about to change."
	),
	"icon": {
		"path": "M4 4h16v16h-16z M8 8h8v8h-8z",
		"color": "#0ea5e9",
		"label": "Dev Agent Repo",
		"stroke": True,
	},
	"execution": {"type": "Python Handler"},
	"operations": [
		{
			"value": "read_file",
			"label": "Read file",
			"description": "Read one file's content from the target app's repository at a given branch.",
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.dev_agent_repo_ops.read_file",
			"fields": [
				{
					"name": "target_app",
					"label": "Target app",
					"type": "Dropdown",
					"required": True,
					"choicesSourcePath": "one_bpmn.one_bpmn.connectors.dev_agent_repo_ops.target_app_choices",
					"help": "Which installed app's repository to read from.",
				},
				{
					"name": "git_branch",
					"label": "Branch",
					"type": "String",
					"required": True,
					"expression": True,
					"help": "Branch to read at. Jinja is allowed, e.g. {{ doc.branch }}.",
				},
				{
					"name": "path",
					"label": "File path",
					"type": "String",
					"required": True,
					"expression": True,
					"help": "Repo-relative path, e.g. one_bpmn/api/github_sync.py.",
				},
			],
			"output": {
				"found": "Whether the file exists at that branch",
				"path": "The path that was read",
				"content": "The file's decoded text content",
			},
		},
		{
			"value": "list_files",
			"label": "List files",
			"description": "List file paths in the target app's repository at a given branch.",
			"executionType": "Python Handler",
			"handlerPath": "one_bpmn.one_bpmn.connectors.dev_agent_repo_ops.list_files",
			"fields": [
				{
					"name": "target_app",
					"label": "Target app",
					"type": "Dropdown",
					"required": True,
					"choicesSourcePath": "one_bpmn.one_bpmn.connectors.dev_agent_repo_ops.target_app_choices",
					"help": "Which installed app's repository to list.",
				},
				{
					"name": "git_branch",
					"label": "Branch",
					"type": "String",
					"required": True,
					"expression": True,
					"help": "Branch to list at. Jinja is allowed, e.g. {{ doc.branch }}.",
				},
				{
					"name": "path_prefix",
					"label": "Path prefix",
					"type": "String",
					"required": False,
					"expression": True,
					"help": "Optional repo-relative prefix to scope the listing, e.g. one_bpmn/api.",
				},
			],
			"output": {
				"files": "List of matching file paths",
				"count": "Number of paths returned",
			},
		},
	],
}


def execute():
	# overwrite=True: the connector carries no site-owned settings (no base
	# URL, no credential — those come from Processa Settings), so re-applying
	# cannot undo local configuration.
	state = import_manifest(DEV_AGENT_REPO_CONNECTOR, overwrite=True)
	print(f"dev_agent_repo connector {state}")

	operations = frappe.get_all(
		"BPMN Connector Operation", filters={"connector": "dev_agent_repo"}, pluck="operation_id"
	)
	if not operations:
		frappe.throw(
			"The dev_agent_repo connector seeded with no operations — the modeler would show it as unusable."
		)
	print(f"  operations: {', '.join(operations)}")
	frappe.clear_cache()
