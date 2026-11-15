"""The agent_sandbox connector gets the run_specs and run_specs_on_base operations the Testing Agent map calls."""

import frappe

from one_bpmn.one_bpmn.connectors.seed import _import_operation
from one_bpmn.one_bpmn.patches.v1_0.add_agent_sandbox_run_tests_and_pull_request_operations import (
	_SHARED_FIELDS,
	CONNECTOR,
	HANDLER,
)

_RUN_ID = {
	"name": "run_id",
	"label": "Run id",
	"type": "String",
	"required": True,
	"help": "The run the specs belong to: the same id prepare_site and checkout_pr_head used.",
}

OPERATIONS = [
	{
		"value": "run_specs",
		"label": "Run the specs on the pull request head",
		"description": (
			"Run the run folder's Playwright specs in Chromium against the site started on the pull request head, with a video "
			"for each. Fails with 'prepare the site first' if the site was not prepared. Parks until the sandbox answers."
		),
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
			"result": "One entry per spec and viewport: criterion, status, failing assertion, duration, video",
		},
		"fields": [*_SHARED_FIELDS, _RUN_ID],
	},
	{
		"value": "run_specs_on_base",
		"label": "Run the changed-behavior specs on the base branch",
		"description": (
			"Restore the snapshot, check the base code out, restart the site and run only the specs tagged changed-behavior, "
			"so a spec that passes without the change is caught. Parks until the sandbox answers."
		),
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
			"result": "The same JSON as run_specs, for the base code",
		},
		"fields": [*_SHARED_FIELDS, _RUN_ID],
	},
]


def execute():
	if not frappe.db.exists("BPMN Connector", CONNECTOR):
		return
	for idx, operation in enumerate(OPERATIONS, start=5):
		_import_operation(CONNECTOR, operation, idx)
