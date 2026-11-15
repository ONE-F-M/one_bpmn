import frappe


def after_install():
	"""Post-install setup for a fresh one_bpmn install.

	Patches are marked complete (not run) on install, so anything a patch
	seeds has to be seeded here as well.
	"""
	from one_bpmn.api.editability import ensure_instance_type_seeded

	ensure_instance_type_seeded()
	frappe.db.commit()


def grant_process_owner_doctype_access():
	"""Give Process Owner read, write and create on DocType, in Custom DocPerm too since the Desk reads it once it has rows."""
	role = "Process Owner"
	if not frappe.db.exists("Role", role):
		return
	grant = {"read": 1, "write": 1, "create": 1, "delete": 0}
	rule = {"parent": "DocType", "role": role, "permlevel": 0, "if_owner": 0}
	tables = ["DocPerm"]
	if frappe.db.exists("Custom DocPerm", {"parent": "DocType"}):
		tables.append("Custom DocPerm")
	for table in tables:
		row = frappe.db.exists(table, rule)
		if row:
			frappe.db.set_value(table, row, grant)
		else:
			frappe.get_doc({
				"doctype": table, "parenttype": "DocType", "parentfield": "permissions", **rule, **grant,
			}).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="DocType")
