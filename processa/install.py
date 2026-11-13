import frappe


def after_install():
	"""Post-install setup for a fresh processa install.

	Patches are marked complete (not run) on install, so anything a patch
	seeds has to be seeded here as well.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from processa.ai_agent_security.code_checks.script_gate import SERVER_SCRIPT_APPROVAL_FIELDS
	from processa.api.editability import ensure_instance_type_seeded
	from processa.processa_engine.notifications.comment_fields import get_comment_custom_fields

	ensure_instance_type_seeded()
	create_custom_fields(SERVER_SCRIPT_APPROVAL_FIELDS)
	create_custom_fields(get_comment_custom_fields())
	frappe.db.commit()


def grant_process_owner_doctype_access():
	"""Give Process Owner read, write and create on DocType, from the standard DocPerm rows Frappe reads for it."""
	role = "Process Owner"
	if not frappe.db.exists("Role", role):
		return
	grant = {"read": 1, "write": 1, "create": 1, "delete": 0}
	row = frappe.db.exists("DocPerm", {"parent": "DocType", "role": role, "permlevel": 0, "if_owner": 0})
	if row:
		frappe.db.set_value("DocPerm", row, grant)
	else:
		frappe.get_doc({
			"doctype": "DocPerm", "parent": "DocType", "parenttype": "DocType",
			"parentfield": "permissions", "role": role, **grant,
		}).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="DocType")
