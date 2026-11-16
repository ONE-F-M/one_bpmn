"""The github connector gets the HTTP operations (get_pull_request, list_pr_files, request_reviewers) on a site that already has it.

A new site gets them with the connector (seed_github_connector). The connector's own Auth Type is not changed here: to sign in as the
GitHub App, set it to GitHub App JSON in the desk and paste the App's JSON into its Auth Secret.
"""

import frappe

from processa.patches.v1_0.seed_github_connector import HTTP_OPERATIONS
from processa.processa_connectors.seed import import_operation


def execute():
	if not frappe.db.exists("BPMN Connector", "github"):
		return
	for idx, operation in enumerate(HTTP_OPERATIONS, start=2):
		import_operation("github", operation, idx)
