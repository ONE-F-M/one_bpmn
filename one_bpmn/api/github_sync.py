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


def read_file(*, token: str, repo: str, path: str, ref: str) -> str | None:
	"""Return the decoded text of ``path`` at ``ref``, or None if absent.

	Needed by callers that have to modify a file they do not own outright — an
	aggregator or patches.txt is appended to, not replaced, so its current content
	has to come back from the branch before the new content can be written.
	"""
	existing = _request(
		"GET", f"{_API}/repos/{repo}/contents/{path}?ref={ref}", token, ok=(200, 404)
	)
	if not existing or not existing.get("content"):
		return None
	return base64.b64decode(existing["content"]).decode("utf-8")


def branch_exists(*, token: str, repo: str, branch: str) -> bool:
	"""True when ``branch`` is present on ``repo``.

	Lets a caller PREFER a base branch without having to assume it exists. A PR
	opened against a missing base fails deep inside pull-request creation, on the
	ref lookup, and surfaces as a bare GitHub 404 — which reads as "GitHub is
	broken" rather than "this repository has no staging branch". Since the
	receiving repository is configurable, not having one is a normal state rather
	than a fault, and the caller needs to be able to tell the difference before
	committing to it.
	"""
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
	"""Create ``head_branch`` off ``base_branch``, commit files, open a PR.

	Args:
		token: GitHub access token with contents:write + pull_requests:write.
		repo: "owner/repo".
		base_branch: branch the PR targets. When falsy, the repository's default
			branch is used.
		head_branch: new branch name to create and push to.
		files: mapping of repo-relative path → file text content. Use this when
			every file is written whole.
		commit_message: message for each file commit.
		pr_title / pr_body: pull request title and body.
		build_files: optional ``fn(reader) -> dict`` called AFTER the head branch
			exists, where ``reader(path)`` returns that path's current text on the
			branch or None. For files that must be appended to rather than
			replaced, which cannot be built before the branch is there to read.
			Its result is merged over ``files``.
		allowed_owners: when non-empty, the repository owner must appear here or
			nothing is pushed. A customization PR is meant for a repo the
			organisation controls; routing one at a third-party upstream would
			put internal schema in someone else's pull request queue.

	Returns:
		The html_url of the created pull request.
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

	# 0) Default the PR base to the repository's default branch.
	if not base_branch:
		info = _request("GET", f"{_API}/repos/{repo}", token)
		base_branch = info.get("default_branch") or "main"

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

	# 3) Files that are edits rather than whole writes are built now, against the
	#    branch that finally exists.
	to_write = dict(files or {})
	if build_files:
		def _reader(path: str):
			return read_file(token=token, repo=repo, path=path, ref=head_branch)

		to_write.update(build_files(_reader) or {})
	if not to_write:
		frappe.throw(_("No files to push."))

	# 4) Commit each file to the head branch via the Contents API.
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

	# 5) Open the pull request.
	pr = _request(
		"POST",
		f"{_API}/repos/{repo}/pulls",
		token,
		json={"title": pr_title, "head": head_branch, "base": base_branch, "body": pr_body},
	)
	return pr.get("html_url", "")
