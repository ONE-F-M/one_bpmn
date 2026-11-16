# Copyright (c) 2026, one-fm and contributors
"""GitHub connector handlers. post_pr_comment puts the Testing Agent's verdict on a pull request as one issue comment.

It only ever creates or edits that one comment. It never calls a review endpoint, so it cannot submit, approve or dismiss a review:
the human reviewer reads the evidence and requests changes if needed.
"""

import json
import re

import frappe
import requests

from processa.processa_connectors.operations import http as http_ops

API = "https://api.github.com"
# A comment may only go on a pull request of these owners, so a model cannot aim the token at someone else's repository.
ALLOWED_OWNERS = ("ONE-F-M",)
MAX_BODY = 60000  # GitHub refuses a comment over 65,536 characters
CELL_LIMIT = 300
_PR_URL = re.compile(r"\Ahttps://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/pull/(\d+)/?\Z")
_RESULTS = ("Pass", "Fail", "Could not test")


class GitHubCommentError(Exception):
	"""A comment that was refused or could not be posted, with a reason the caller can act on."""


def _cell(text, limit=CELL_LIMIT):
	text = re.sub(r"\s+", " ", str(text or "")).strip().replace("|", "\\|")
	return text if len(text) <= limit else text[: limit - 1] + "…"


def _criterion_id(criterion):
	match = re.match(r"^\s*(AC\s*\d+)", str(criterion or ""), re.I)
	return re.sub(r"\s+", "", match.group(1)).upper() if match else _cell(criterion, 40)


def render_comment(summary, routing_reason, verdict, run_id=""):
	"""The comment text: a first line 'Acceptance test: X of Y criteria passed'; the routing line; a table of criterion, result and
	evidence; a video URL on its own line under each criterion; and the Could not test reasons. No traces are linked."""
	rows = [v for v in verdict if isinstance(v, dict)]
	passed = len([v for v in rows if v.get("result") == "Pass"])
	lines = [f"Acceptance test: {passed} of {len(rows)} criteria passed", ""]
	if routing_reason:
		lines += [f"Routing: {_cell(routing_reason, 400)}", ""]
	if summary:
		lines += [_cell(summary, 600), ""]
	lines += ["| Criterion | Result | Evidence |", "|---|---|---|"]
	for v in rows:
		lines.append(f"| {_cell(v.get('criterion'), 120)} | {v.get('result') if v.get('result') in _RESULTS else 'Could not test'} | {_cell(v.get('evidence') or v.get('reason'))} |")
	videos = [v for v in rows if v.get("video_url")]
	if videos:
		lines += ["", "Videos"]
		for v in videos:
			lines += ["", f"{_criterion_id(v.get('criterion'))}:", str(v["video_url"]).strip()]
	untested = [v for v in rows if v.get("result") not in ("Pass", "Fail")]
	if untested:
		lines += ["", "Could not test"]
		lines += [f"- {_criterion_id(v.get('criterion'))}: {_cell(v.get('reason') or v.get('evidence'), 400)}" for v in untested]
	if run_id:
		lines += ["", f"<!-- testing-agent run:{re.sub(r'[^A-Za-z0-9_-]', '', str(run_id))} -->"]
	body = "\n".join(lines)
	return body if len(body) <= MAX_BODY else body[: MAX_BODY - 40] + "\n\n(comment shortened)"


CONNECTOR = "github"


def _token():
	"""The token the comment is posted with. When the github connector signs in as the GitHub App (Auth Type GitHub App JSON), it is the
	App's installation token, and a missing or refused key fails the call: it never falls back to a personal token. Otherwise it is the
	connector's Auth Secret when it is enabled with Bearer Token auth, else the GitHub Token in Processa Settings."""
	row = frappe.db.get_value("BPMN Connector", CONNECTOR, ["enabled", "auth_type"], as_dict=True)
	if row and row.enabled and row.auth_type == "GitHub App JSON":
		from processa.processa_connectors import manifest

		try:
			return http_ops._github_app_token(manifest.get_execution_spec(CONNECTOR, "post_pr_comment"))
		except http_ops.ConnectorHTTPError as e:
			raise GitHubCommentError(str(e)) from e
	if row and row.enabled and row.auth_type == "Bearer Token":
		secret = (frappe.get_doc("BPMN Connector", CONNECTOR).get_password("auth_secret", raise_exception=False) or "").strip()
		if secret:
			return secret
	token = frappe.get_cached_doc("Processa Settings").get_password("github_token", raise_exception=False) or ""
	if not token:
		raise GitHubCommentError("No GitHub token: set the Auth Secret on the github connector, or the GitHub Token in Processa Settings.")
	return token


def _call(method, url, token, payload=None):
	response = requests.request(
		method, url, timeout=30, json=payload,
		headers={**http_ops.github_headers(), "Authorization": f"Bearer {token}"},
	)
	if response.status_code >= 300:
		raise GitHubCommentError(f"GitHub answered {response.status_code} for {method} {url.replace(API, '')}: {response.text[:200]}")
	return response.json()


def _existing_comment(base, marker, token):
	"""The comment this run already posted (found by its hidden marker), so a rerun edits it rather than adding a second."""
	for page in range(1, 6):
		batch = _call("GET", f"{base}/comments?per_page=100&page={page}", token)
		for comment in batch:
			if marker in (comment.get("body") or ""):
				return comment
		if len(batch) < 100:
			break
	return None


def post_pr_comment(params, ctx):
	"""Post (or update) the verdict comment on a pull request. params: pr_url, verdict (a list of criterion/result/evidence/video_url),
	summary, routing_reason, run_id. Returns the comment's url and id."""
	match = _PR_URL.match(str(params.get("pr_url") or "").strip())
	if not match:
		raise GitHubCommentError("pr_url must be a https://github.com/<owner>/<repo>/pull/<number> link.")
	owner, repo, number = match.groups()
	if owner not in ALLOWED_OWNERS:
		raise GitHubCommentError(f"Comments are only posted on pull requests of {', '.join(ALLOWED_OWNERS)}, not {owner}.")
	verdict = params.get("verdict")
	if isinstance(verdict, str):
		try:
			verdict = json.loads(verdict)
		except ValueError:
			raise GitHubCommentError("verdict must be a JSON list.") from None
	if not isinstance(verdict, list) or not verdict:
		raise GitHubCommentError("verdict is required: a list with one entry per criterion.")
	run_id = re.sub(r"[^A-Za-z0-9_-]", "", str(params.get("run_id") or ""))
	body = render_comment(params.get("summary"), params.get("routing_reason"), verdict, run_id)
	token = _token()
	base = f"{API}/repos/{owner}/{repo}/issues/{number}"
	existing = _existing_comment(base, f"<!-- testing-agent run:{run_id} -->", token) if run_id else None
	if existing:
		done = _call("PATCH", f"{API}/repos/{owner}/{repo}/issues/comments/{existing['id']}", token, {"body": body})
	else:
		done = _call("POST", f"{base}/comments", token, {"body": body})
	return {"comment_url": done.get("html_url"), "comment_id": done.get("id"), "updated": bool(existing)}
