# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from one_bpmn.agents_sandbox.customization.github_sync import org_repos


def list_org_repos(org: str = "ONE-F-M") -> list[dict]:
	"""Cross-app entry point: frappe_agile's own repo-picker sync (Work Item's
	target_app Link field) has no GitHub credential of its own — this reuses
	the one already configured on Processa Settings for the Dev Agent sandbox,
	rather than a second token existing purely to duplicate it.

	A plain Python call from another app on the same site (both apps share
	one process), not an HTTP round trip to itself."""
	token = frappe.get_cached_doc("Processa Settings").get_password("github_token", raise_exception=False) or ""
	if not token:
		frappe.throw(_("Processa Settings has no GitHub token configured."))
	return org_repos(token, org)
