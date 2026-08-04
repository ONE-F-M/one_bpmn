# Copyright (c) 2026, one-fm and contributors
# The generic connector layer no longer knows about Google Drive. Field types
# DriveFile/DriveFolder were Google concepts baked into the shared enum, and the
# dispatcher hardcoded "if the type is one of those, normalise the value".
#
# Both are now configuration: the type is a plain input and the normalisation is
# a per-field Value Transform (a dotted path to fn(value) -> value). This
# converts rows created under the old schema.
#
# Runs before the DocType Select drops the old options, so it uses db_set-style
# direct updates rather than doc.save (which would reject the old value).

import frappe

_DRIVE_ID_TRANSFORM = "one_bpmn.one_bpmn.integrations.google_common.normalize_drive_id"
_LEGACY_TYPES = ("DriveFile", "DriveFolder")


def execute():
	for doctype in ("BPMN Connector Field", "BPMN Connector Operation", "BPMN Connector"):
		frappe.reload_doctype(doctype)

	if not frappe.db.table_exists("BPMN Connector Field"):
		return

	rows = frappe.get_all(
		"BPMN Connector Field",
		filters={"field_type": ("in", _LEGACY_TYPES)},
		fields=["name", "field_type", "value_transform"],
	)
	if not rows:
		return

	for row in rows:
		frappe.db.set_value(
			"BPMN Connector Field",
			row.name,
			{
				"field_type": "String",
				# Never clobber a transform someone already set by hand.
				"value_transform": row.value_transform or _DRIVE_ID_TRANSFORM,
			},
			update_modified=False,
		)

	# Old rows may also carry the retired free-text choices_from; move it to the
	# dotted-path field so dynamic dropdowns keep resolving.
	if frappe.db.has_column("BPMN Connector Field", "choices_from"):
		for name, source in frappe.db.get_all(
			"BPMN Connector Field",
			filters={"choices_from": ("is", "set")},
			fields=["name", "choices_from"],
			as_list=True,
		):
			if source == "driveFiles":
				source = "one_bpmn.one_bpmn.connectors.google_drive_ops.list_file_choices"
			frappe.db.set_value(
				"BPMN Connector Field", name, "choices_source_path", source, update_modified=False
			)

	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()
	print(f"Converted {len(rows)} Drive-typed connector field(s) to a Value Transform")
