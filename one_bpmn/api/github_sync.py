# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# Thin GitHub REST client used by "Review Doctypes" → "Sync" to raise a pull
# request carrying DocType schema changes (Custom Fields + Property Setters).
#
# It operates entirely through the GitHub REST API (create branch ref → commit
# file contents → open PR) so it does not depend on a local git remote being
# configured on the bench. It stays inert until a token + repository mapping are
# filled in on Processa Settings.

import base64

import frappe
from frappe import _

_API = "https://api.github.com"


def _headers(token: str) -> dict:
	return {
		"Authorization": f"Bearer {token}",
		"Accept": "application/vnd.github+json",
		"X-GitHub-Api-Version": "2022-11-28",
	}


def _request(method: str, url: str, token: str, ok=(200, 201), **kwargs):
	import requests

	resp = requests.request(method, url, headers=_headers(token), timeout=30, **kwargs)
	if resp.status_code not in ok:
		# 404 is meaningful to some callers (e.g. "file not yet present").
		if resp.status_code == 404 and 404 in ok:
			return None
		frappe.log_error(
			title="GitHub API call failed",
			message=f"{method} {url}\nStatus: {resp.status_code}\nBody: {resp.text[:2000]}",
		)
		frappe.throw(
			_("GitHub API error ({0}) on {1}: {2}").format(
				resp.status_code, url.replace(_API, ""), resp.text[:300]
			)
		)
	return resp.json() if resp.text else {}


def open_customization_pr(
	*,
	token: str,
	repo: str,
	base_branch: str,
	head_branch: str,
	files: dict,
	commit_message: str,
	pr_title: str,
	pr_body: str,
) -> str:
	"""Create ``head_branch`` off ``base_branch``, commit ``files``, open a PR.

	Args:
		token: GitHub access token with contents:write + pull_requests:write.
		repo: "owner/repo".
		base_branch: branch the PR targets (e.g. "develop").
		head_branch: new branch name to create and push to.
		files: mapping of repo-relative path → file text content.
		commit_message: message for each file commit.
		pr_title / pr_body: pull request title and body.

	Returns:
		The html_url of the created pull request.
	"""
	if not token:
		frappe.throw(_("GitHub Access Token is not configured in Processa Settings."))
	if not repo or "/" not in repo:
		frappe.throw(_("Invalid GitHub repository (expected owner/repo): {0}").format(repo))
	if not files:
		frappe.throw(_("No files to push."))

	# 1) Resolve base branch SHA.
	ref = _request("GET", f"{_API}/repos/{repo}/git/ref/heads/{base_branch}", token)
	base_sha = ref["object"]["sha"]

	# 2) Create the head branch from base (ignore "already exists").
	_request(
		"POST",
		f"{_API}/repos/{repo}/git/refs",
		token,
		ok=(201, 422),
		json={"ref": f"refs/heads/{head_branch}", "sha": base_sha},
	)

	# 3) Commit each file to the head branch via the Contents API.
	for path, content in files.items():
		existing = _request(
			"GET",
			f"{_API}/repos/{repo}/contents/{path}?ref={head_branch}",
			token,
			ok=(200, 404),
		)
		payload = {
			"message": commit_message,
			"content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
			"branch": head_branch,
		}
		if existing and existing.get("sha"):
			payload["sha"] = existing["sha"]
		_request("PUT", f"{_API}/repos/{repo}/contents/{path}", token, json=payload)

	# 4) Open the pull request.
	pr = _request(
		"POST",
		f"{_API}/repos/{repo}/pulls",
		token,
		json={"title": pr_title, "head": head_branch, "base": base_branch, "body": pr_body},
	)
	return pr.get("html_url", "")
