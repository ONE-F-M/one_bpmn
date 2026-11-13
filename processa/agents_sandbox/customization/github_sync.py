# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
"""GitHub REST client that opens Review Doctypes Sync pull requests through the Contents API, with no local git remote."""

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


def read_file(*, token: str, repo: str, path: str, ref: str) -> str | None:
	"""Return the decoded text of ``path`` at ``ref``, or None if absent."""
	existing = _request(
		"GET", f"{_API}/repos/{repo}/contents/{path}?ref={ref}", token, ok=(200, 404)
	)
	if not existing or not existing.get("content"):
		return None
	return base64.b64decode(existing["content"]).decode("utf-8")


def branch_exists(*, token: str, repo: str, branch: str) -> bool:
	"""True when ``branch`` is present on ``repo``, so a caller can prefer a base branch that may not exist."""
	ref = _request(
		"GET", f"{_API}/repos/{repo}/git/ref/heads/{branch}", token, ok=(200, 404)
	)
	return bool(ref and (ref.get("object") or {}).get("sha"))


def open_customization_pr(
	*,
	token: str,
	repo: str,
	base_branch: str | None,
	head_branch: str,
	files: dict = None,
	commit_message: str,
	pr_title: str,
	pr_body: str,
	build_files=None,
	allowed_owners: tuple = (),
) -> str:
	"""Create ``head_branch`` off ``base_branch``, commit ``files`` and ``build_files(reader)``, open a PR.

	A falsy base means the repository's default branch. Returns the pull request html_url.
	"""
	if not token:
		frappe.throw(_("GitHub Access Token is not configured in Processa Settings."))
	if not repo or "/" not in repo:
		frappe.throw(_("Invalid GitHub repository (expected owner/repo): {0}").format(repo))
	if not files and not build_files:
		frappe.throw(_("No files to push."))

	if allowed_owners:
		owner = repo.split("/")[0].lower()
		if owner not in {o.lower() for o in allowed_owners}:
			frappe.throw(
				_(
					"Refusing to open a pull request against '{0}': its owner is not one of {1}. "
					"Set the customization owner app in Processa Settings so the change is routed "
					"to a repository you control."
				).format(repo, ", ".join(allowed_owners)),
				title=_("Unexpected Repository"),
			)

	if not base_branch:
		info = _request("GET", f"{_API}/repos/{repo}", token)
		base_branch = info.get("default_branch") or "main"

	ref = _request("GET", f"{_API}/repos/{repo}/git/ref/heads/{base_branch}", token)
	base_sha = ref["object"]["sha"]

	# 422 means the head branch already exists.
	_request(
		"POST",
		f"{_API}/repos/{repo}/git/refs",
		token,
		ok=(201, 422),
		json={"ref": f"refs/heads/{head_branch}", "sha": base_sha},
	)

	# Appended files are built against the head branch once it exists.
	to_write = dict(files or {})
	if build_files:
		def _reader(path: str):
			return read_file(token=token, repo=repo, path=path, ref=head_branch)

		to_write.update(build_files(_reader) or {})
	if not to_write:
		frappe.throw(_("No files to push."))

	for path, content in to_write.items():
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

	pr = _request(
		"POST",
		f"{_API}/repos/{repo}/pulls",
		token,
		json={"title": pr_title, "head": head_branch, "base": base_branch, "body": pr_body},
	)
	return pr.get("html_url", "")


def org_repos(token: str, org: str) -> list[dict]:
	"""Every repository in *org*, forks and archived ones included, 100 per page."""
	repos = []
	page = 1
	while True:
		batch = _request(
			"GET", f"{_API}/orgs/{org}/repos?per_page=100&page={page}", token
		)
		if not batch:
			break
		repos.extend(batch)
		if len(batch) < 100:
			break
		page += 1
	return [
		{"name": r["name"], "description": r.get("description") or "", "html_url": r["html_url"]}
		for r in repos
	]
