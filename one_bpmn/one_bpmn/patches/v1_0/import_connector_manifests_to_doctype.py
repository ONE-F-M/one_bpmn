# Copyright (c) 2026, one-fm and contributors
# Connectors became configuration: the JSON manifests under connectors/manifests/
# are now the *seed* for the BPMN Connector / Operation / Field DocTypes, which
# hold the live definitions. This imports the shipped manifests so existing sites
# keep the four Google connectors after the loader flips to the database.
#
# Idempotent and non-destructive: a connector that already exists is skipped, so
# re-running never clobbers a site's own edits to a shipped connector.

import frappe

from one_bpmn.one_bpmn.connectors.seed import import_seed_manifests


def execute():
	for doctype in ("BPMN Connector", "BPMN Connector Operation", "BPMN Connector Field"):
		frappe.reload_doctype(doctype)

	results = import_seed_manifests(overwrite=False)
	created = sorted(cid for cid, state in results.items() if state == "created")
	skipped = sorted(cid for cid, state in results.items() if state == "skipped")

	if created:
		print(f"Imported connectors: {', '.join(created)}")
	if skipped:
		print(f"Connectors already configured, left untouched: {', '.join(skipped)}")
