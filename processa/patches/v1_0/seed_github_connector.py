"""Seed the "github" Connector with the post_pr_comment operation the Testing Agent map publishes its verdict through."""

import frappe

HANDLER = "processa.processa_connectors.operations.github.post_pr_comment"

GITHUB_CONNECTOR = {
	"connectorId": "github",
	"label": "GitHub",
	"description": "Posts the Testing Agent's verdict on a pull request. It only creates or edits one issue comment; it never submits, approves or dismisses a review.",
	"execution": {
		"type": "HTTP Request", "baseUrl": "https://api.github.com", "timeout": 30,
		"auth": {"type": "GitHub App JSON", "source": "On this connector"},
	},
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


_NUMBER = {"name": "number", "label": "Pull request number", "type": "String", "required": True}
_OWNER = {"name": "owner", "label": "Owner", "type": "String", "required": True, "help": "The organisation, such as ONE-F-M."}
_REPO = {"name": "repo", "label": "Repository", "type": "String", "required": True, "help": "The repository name, such as processa."}
_PR_URL = "repos/{{ params.owner }}/{{ params.repo }}/pulls/{{ params.number }}"

# Plain HTTP operations: the connector signs in as the GitHub App (Auth Type GitHub App JSON) and sends GitHub's headers itself.
HTTP_OPERATIONS = [
	{
		"value": "get_pull_request",
		"label": "Read a pull request",
		"description": "The pull request's number, title, state, whether it merged, its head commit, base branch, author, link and size.",
		"executionType": "HTTP Request",
		"http": {
			"method": "GET",
			"url": _PR_URL,
			"responseMap": {
				"number": "number", "title": "title", "state": "state", "merged": "merged", "head_sha": "head.sha", "base_ref": "base.ref",
				"author": "user.login", "html_url": "html_url", "changed_files": "changed_files", "additions": "additions", "deletions": "deletions",
			},
		},
		"fields": [_OWNER, _REPO, _NUMBER],
	},
	{
		"value": "list_pr_files",
		"label": "List a pull request's files",
		"description": "One page (up to 100) of the files a pull request changes, with the additions and deletions of each.",
		"executionType": "HTTP Request",
		"http": {
			"method": "GET",
			"url": _PR_URL + "/files",
			"query": {"per_page": "100", "page": "{{ params.page or 1 }}"},
			"responseMap": {"files": ""},
		},
		"fields": [_OWNER, _REPO, _NUMBER, {"name": "page", "label": "Page", "type": "String", "required": False, "help": "1 by default."}],
	},
	{
		"value": "request_reviewers",
		"label": "Request reviewers on a pull request",
		"description": "Asks the listed people and teams to review the pull request. It requests a review; it never submits or approves one.",
		"executionType": "HTTP Request",
		"http": {
			"method": "POST",
			"url": _PR_URL + "/requested_reviewers",
			"contentType": "application/json",
			"body": '{"reviewers": {{ (params.reviewers or "").split(",") | map("trim") | select | list | tojson }}, '
			'"team_reviewers": {{ (params.team_reviewers or "").split(",") | map("trim") | select | list | tojson }}}',
			"responseMap": {"html_url": "html_url"},
		},
		"fields": [
			_OWNER, _REPO, _NUMBER,
			{"name": "reviewers", "label": "Reviewers", "type": "Text", "required": False, "help": "GitHub logins, separated by commas."},
			{"name": "team_reviewers", "label": "Team reviewers", "type": "Text", "required": False, "help": "Team slugs, separated by commas."},
		],
	},
]
GITHUB_CONNECTOR["operations"].extend(HTTP_OPERATIONS)


def execute():
	from processa.processa_connectors.seed import import_manifest

	import_manifest(GITHUB_CONNECTOR, overwrite=False)
	frappe.db.commit()
