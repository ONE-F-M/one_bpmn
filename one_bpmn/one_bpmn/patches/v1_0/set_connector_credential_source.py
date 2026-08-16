# Copyright (c) 2026, one-fm and contributors
# A connector can now hold its own credential (an encrypted Password field on
# BPMN Connector) instead of pointing at a Password field on a settings DocType.
# On-connector is the new default, because it removes the only step of building a
# connector that used to need Customize Form.
#
# Connectors configured before this change point at a settings DocType, so they
# are pinned to that source explicitly — otherwise the new default would silently
# look for an on-connector secret that was never set, and their calls would start
# failing with "no secret found".

import frappe


def execute():
	frappe.reload_doctype("BPMN Connector")

	if not frappe.db.table_exists("BPMN Connector"):
		return

	pinned = 0
	for name in frappe.get_all(
		"BPMN Connector",
		filters={"auth_settings_doctype": ("is", "set"), "auth_secret_field": ("is", "set")},
		pluck="name",
	):
		frappe.db.set_value(
			"BPMN Connector", name, "credential_source", "From a settings DocType",
			update_modified=False,
		)
		pinned += 1

	# Everything else takes the default. Written explicitly so the field is never
	# empty at runtime (an empty Select would fall through to the on-connector
	# branch anyway, but a real value is what the form and the export should show).
	for name in frappe.get_all(
		"BPMN Connector", filters={"credential_source": ("in", ("", None))}, pluck="name"
	):
		frappe.db.set_value(
			"BPMN Connector", name, "credential_source", "On this connector", update_modified=False
		)

	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()
	if pinned:
		print(f"Pinned {pinned} connector(s) to their existing settings-DocType credential")
