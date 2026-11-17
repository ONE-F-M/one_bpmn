"""The apps the sandbox image holds, as the sandbox itself reports them when a session registers.

Processa checks a dispatch against this list, so a repository becomes dispatchable the moment it is in the image and nobody keeps a second
list by hand. A Work Item names a GitHub repository (password_management, agent-sandbox) while the image holds an app folder
(one_fm_password_management, agent_sandbox), so both names are accepted.
"""

import json
import re

import frappe

SETTINGS = "Processa Settings"
_APP = re.compile(r"\A[A-Za-z0-9_]{1,64}\Z")
_REPO = re.compile(r"\A[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
MAX_APPS = 100


def clean(apps) -> list[dict]:
	"""The usable entries of a report: {"app": a safe app name, "repository": "owner/name" or ""}, one per app, at most MAX_APPS."""
	if not isinstance(apps, list):
		return []
	found, seen = [], set()
	for entry in apps:
		if not isinstance(entry, dict):
			continue
		app, repository = str(entry.get("app") or ""), str(entry.get("repository") or "")
		if not _APP.match(app) or app in seen or (repository and not _REPO.match(repository)):
			continue
		seen.add(app)
		found.append({"app": app, "repository": repository})
		if len(found) == MAX_APPS:
			break
	return found


def record(apps) -> int:
	"""Keep what the sandbox reported. An empty or unusable report leaves the last good one in place. Returns how many apps were kept."""
	entries = clean(apps)
	if entries:
		frappe.db.set_single_value(SETTINGS, "sandbox_reported_apps", json.dumps(entries))
		frappe.db.set_single_value(SETTINGS, "sandbox_reported_apps_at", frappe.utils.now())
	return len(entries)


def reported() -> list[dict]:
	"""The last report, or [] before the sandbox has sent one."""
	try:
		return clean(json.loads(frappe.db.get_single_value(SETTINGS, "sandbox_reported_apps") or "[]"))
	except ValueError:
		return []


def app_names() -> list[str]:
	return [entry["app"] for entry in reported()]


def repository_names() -> list[str]:
	"""The repository names (the part after owner/) that a Work Item may carry for a reported app."""
	return [entry["repository"].split("/")[-1] for entry in reported() if entry["repository"]]
