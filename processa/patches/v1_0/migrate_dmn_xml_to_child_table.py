"""Migrate legacy flat dmn_xml field to the new decision_tables child table.

Any BPMN Process Model that has a non-empty dmn_xml value gets a single
Workflow Decision Table row with decision_id='legacy_dmn'.
"""
import frappe


def execute():
	# Check if the old column still exists (it will be dropped by migrate)
	if not frappe.db.has_column("BPMN Process Model", "dmn_xml"):
		return

	# Find all models with non-empty dmn_xml
	models_with_dmn = frappe.get_all(
		"BPMN Process Model",
		filters=[["dmn_xml", "is", "set"]],
		fields=["name", "dmn_xml"],
	)

	if not models_with_dmn:
		return

	migrated = 0
	for model in models_with_dmn:
		# Skip if already migrated (has a child row with this decision_id)
		existing = frappe.db.exists(
			"Workflow Decision Table",
			{"parent": model.name, "decision_id": "legacy_dmn"},
		)
		if existing:
			continue

		doc = frappe.get_doc("BPMN Process Model", model.name)
		doc.flags.skip_editability_check = True
		doc.append("decision_tables", {
			"decision_id": "legacy_dmn",
			"decision_name": "Legacy DMN (migrated)",
			"dmn_xml": model.dmn_xml,
		})
		doc.save(ignore_permissions=True)
		migrated += 1

	if migrated:
		frappe.db.commit()
		print(f"Migrated {migrated} BPMN Process Model(s) dmn_xml → decision_tables")
