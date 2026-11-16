"""Seed the "github" Connector with the post_pr_comment operation the Testing Agent map publishes its verdict through."""

import frappe

HANDLER = "processa.processa_connectors.operations.github.post_pr_comment"

GITHUB_CONNECTOR = {
	"connectorId": "github",
	"label": "GitHub",
	"description": "Posts the Testing Agent's verdict on a pull request. It only creates or edits one issue comment; it never submits, approves or dismisses a review.",
	"execution": {"type": "HTTP Request", "baseUrl": "https://api.github.com", "timeout": 30},
	"operations": [
		{
			"value": "post_pr_comment",
			"label": "Post the verdict on a pull request",
			"description": (
				"One comment on the pull request: 'Acceptance test: X of Y criteria passed', the routing line, a table of criterion, "
				"result and evidence, a video URL on its own line under each criterion, and the Could not test reasons. A rerun of the "
				"same run edits its comment instead of adding another. Only pull requests of the allowed owner are accepted."
			),
			"executionType": "Python Handler",
			"handlerPath": HANDLER,
			"output": {"comment_url": "The comment's link", "comment_id": "Its id", "updated": "True when an earlier comment of this run was edited"},
			"fields": [
				{"name": "pr_url", "label": "Pull request URL", "type": "String", "required": True, "help": "https://github.com/<owner>/<repo>/pull/<number>"},
				{"name": "verdict", "label": "Verdict", "type": "Text", "required": True, "help": "A JSON list: one entry per criterion with criterion, result, evidence or reason, and video_url."},
				{"name": "summary", "label": "Summary", "type": "Text", "required": False, "help": "One line shown under the first line."},
				{"name": "routing_reason", "label": "Routing reason", "type": "Text", "required": False, "help": "Why the PR went to Sonnet or Opus."},
				{"name": "run_id", "label": "Run id", "type": "String", "required": False, "help": "Makes a rerun edit the same comment."},
			],
		}
	],
}


def execute():
	from processa.processa_connectors.seed import import_manifest

	import_manifest(GITHUB_CONNECTOR, overwrite=False)
	frappe.db.commit()
