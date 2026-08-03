# Copyright (c) 2026, one-fm and contributors
# Add shipped operations that a site's already-imported connectors are missing.
#
# The seed patch deliberately **skips a connector that already exists** so
# re-running it can never clobber a site's own edits to a shipped connector. That
# is the right call for the connector as a whole, and it leaves a gap: when a
# later release adds an *operation* to a shipped manifest, sites that already
# imported get the Python handler but no BPMN Connector Operation to select it
# with. The handler is registered and unreachable — `validate_manifests` reports
# exactly that ("registered handler is not configured as a BPMN Connector
# Operation, so no modeler can select it").
#
# This closes the gap additively: every operation in a shipped manifest that has
# no record yet is created; every operation that already has one is left exactly
# as the site configured it. Nothing is overwritten, so a site that renamed a
# label or disabled an operation keeps those choices.
#
# Written when merging brought `copyFile`, `revokePermissions` and `fillTemplate`
# into the shipped Google set, but it is not specific to them — it will pick up
# whatever a future manifest adds.

import frappe


def execute():
	for doctype in ("BPMN Connector", "BPMN Connector Operation", "BPMN Connector Field"):
		frappe.reload_doctype(doctype)

	from one_bpmn.one_bpmn.patches.v1_0.seed_google_connectors import GOOGLE_CONNECTORS
	from one_bpmn.one_bpmn.connectors.seed import _import_operation

	added = []
	for manifest in GOOGLE_CONNECTORS:
		cid = (manifest.get("connectorId") or "").strip()
		# A connector that was never imported is the other patch's job; creating
		# a bare operation here would leave it parented to nothing.
		if not cid or not frappe.db.exists("BPMN Connector", cid):
			continue

		for idx, op in enumerate(manifest.get("operations") or []):
			op_id = (op.get("value") or "").strip()
			if not op_id:
				continue
			if frappe.db.exists(
				"BPMN Connector Operation", {"connector": cid, "operation_id": op_id}
			):
				continue

			_import_operation(cid, op, idx, overwrite=False)
			added.append(f"{cid}/{op_id}")

	frappe.db.commit()
	print(
		f"Added {len(added)} missing connector operation(s): {', '.join(added)}"
		if added
		else "No missing connector operations."
	)
