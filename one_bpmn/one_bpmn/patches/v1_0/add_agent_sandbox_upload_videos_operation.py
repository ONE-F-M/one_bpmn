"""The agent_sandbox connector gets the upload_videos operation the Testing Agent map calls."""

import frappe

from one_bpmn.one_bpmn.connectors.seed import _import_operation
from one_bpmn.one_bpmn.patches.v1_0.add_agent_sandbox_run_tests_and_pull_request_operations import (
	_SHARED_FIELDS,
	CONNECTOR,
	HANDLER,
)

OPERATIONS = [
	{
		"value": "upload_videos",
		"label": "Upload the test videos to the pull request's repository",
		"description": (
			"Upload one video per criterion from the head run and return the user-attachments links. The machine user's token "
			"comes from the github_video_upload connector, never from the map. If the upload endpoint refuses the token, the "
			"machine user posts the comment itself. Parks until the sandbox answers."
		),
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": {
			"run": "The Agent Sandbox Run record tracking this dispatch",
			"state": "Final state: completed or failed",
			"result": "One link per criterion, or the error for each criterion that did not upload",
		},
		"fields": [
			*_SHARED_FIELDS,
			{"name": "run_id", "label": "Run id", "type": "String", "required": True, "help": "The run whose videos are uploaded."},
			{"name": "repository", "label": "Repository", "type": "String", "required": True, "help": "owner/name of the pull request's repository, such as ONE-F-M/one_bpmn."},
			{"name": "pr_number", "label": "Pull request number", "type": "String", "required": True, "help": "The pull request the comment belongs to."},
			{
				"name": "comment_body", "label": "Comment text", "type": "Text", "required": False,
				"help": "Only used if the upload endpoint refuses the token: the whole comment the machine user then posts.",
			},
		],
	},
]


def execute():
	if not frappe.db.exists("BPMN Connector", CONNECTOR):
		return
	for idx, operation in enumerate(OPERATIONS, start=7):
		_import_operation(CONNECTOR, operation, idx)
