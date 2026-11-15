"""The agent_sandbox connector gets the prepare_site and checkout_pr_head operations the Testing Agent map calls."""

import frappe

from processa.processa_connectors.seed import import_operation
from processa.patches.v1_0.add_agent_sandbox_run_tests_and_pull_request_operations import (
	_SHARED_FIELDS,
	CONNECTOR,
	HANDLER,
)

_RUN_FIELDS = [
	{
		"name": "run_id",
		"label": "Run id",
		"type": "String",
		"required": True,
		"help": "Names this test run: letters, digits, - and _. Its snapshot is saved under this name, and prepare_site and checkout_pr_head must use the same one.",
	},
	{
		"name": "pr_number",
		"label": "Pull request number",
		"type": "String",
		"required": True,
		"help": "The pull request's number. The sandbox fetches refs/pull/<number>/head.",
	},
]

OPERATIONS = [
	{
		"value": "prepare_site",
		"label": "Prepare the test site",
		"description": (
			"Check out the base branch, migrate the sandbox site, create one test user per role plus one with none of them, "
			"mute emails and save a database snapshot. Parks until the sandbox answers."
		),
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
			"result": "The users created, the base commit and the snapshot path",
		},
		"fields": [
			*_SHARED_FIELDS,
			*_RUN_FIELDS,
			{
				"name": "base_branch",
				"label": "Base branch",
				"type": "String",
				"required": True,
				"help": "The branch the pull request targets; the snapshot is taken on it.",
			},
			{
				"name": "roles",
				"label": "Roles",
				"type": "Text",
				"required": True,
				"help": "The roles to test, one per line or separated by commas. Each gets its own test user.",
			},
			{
				"name": "password",
				"label": "Test password",
				"type": "String",
				"required": True,
				"help": "The one password every test user gets. It is not stored on the run record.",
			},
		],
	},
	{
		"value": "checkout_pr_head",
		"label": "Check out the pull request head and start the site",
		"description": (
			"Fetch the pull request's head commit, check it out, rebuild assets only if the change needs it, migrate, and start "
			"the site and one worker. Succeeds only when the site answers /api/method/ping. Parks until the sandbox answers."
		),
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
			"result": "The head commit, whether assets were built and the port",
		},
		"fields": [*_SHARED_FIELDS, *_RUN_FIELDS],
	},
]


def execute():
	if not frappe.db.exists("BPMN Connector", CONNECTOR):
		return
	for idx, operation in enumerate(OPERATIONS, start=3):
		import_operation(CONNECTOR, operation, idx)
