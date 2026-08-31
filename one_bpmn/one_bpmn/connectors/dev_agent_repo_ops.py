# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Read-only GitHub access for Dev Agent's own planning step.

Dev Agent's ``work`` ai_agent task must see a target app's actual source
before it can propose real file changes — dispatch_to_sandbox alone gives it
nowhere to look. These two tools read straight from GitHub at the exact
target_app/git_branch being planned against, rather than from this bench's
own local checkout, which could be on a different branch or commit entirely.

Both operations answer synchronously (a GitHub API call, seconds at most) —
unlike dev_agent_sandbox_ops.dispatch, there is no park/suspend here.
"""

from __future__ import annotations

import frappe

from one_bpmn.api.github_sync import list_files as _gh_list_files
from one_bpmn.api.github_sync import read_file as _gh_read_file
from one_bpmn.api.production_review import _repo_for_app


class DevAgentRepoError(Exception):
	"""Raised for a read failure the model should be told about plainly."""


def target_app_choices() -> list[str]:
	return frappe.get_installed_apps()


def _resolve(target_app: str) -> tuple[str, str]:
	target_app = (target_app or "").strip()
	if not target_app:
		raise DevAgentRepoError("target_app is required.")
	repo = _repo_for_app(target_app)
	if not repo:
		raise DevAgentRepoError(f"No GitHub repository configured for {target_app!r}.")
	token = frappe.get_cached_doc("Processa Settings").get_password("github_token")
	if not token:
		raise DevAgentRepoError("Processa Settings has no GitHub token configured.")
	return repo, token


def read_file(params: dict, ctx: dict) -> dict:
	"""Return one file's content at the given branch, or found=False."""
	git_branch = (params.get("git_branch") or "").strip()
	path = (params.get("path") or "").strip()
	if not git_branch:
		raise DevAgentRepoError("git_branch is required.")
	if not path:
		raise DevAgentRepoError("path is required.")

	repo, token = _resolve(params.get("target_app"))
	content = _gh_read_file(token=token, repo=repo, path=path, ref=git_branch)
	if content is None:
		return {"found": False, "path": path, "content": ""}
	return {"found": True, "path": path, "content": content}


def list_files(params: dict, ctx: dict) -> dict:
	"""List file paths at the given branch, optionally scoped to a prefix."""
	git_branch = (params.get("git_branch") or "").strip()
	if not git_branch:
		raise DevAgentRepoError("git_branch is required.")

	repo, token = _resolve(params.get("target_app"))
	paths = _gh_list_files(
		token=token, repo=repo, ref=git_branch, path_prefix=params.get("path_prefix") or ""
	)
	return {"files": paths, "count": len(paths)}
