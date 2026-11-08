import frappe


def after_install():
	"""Post-install setup for a fresh one_bpmn install.

	Patches are marked complete (not run) on install, so anything a patch
	seeds has to be seeded here as well.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from one_bpmn.api.editability import ensure_instance_type_seeded
	from one_bpmn.security.script_gate import SERVER_SCRIPT_APPROVAL_FIELDS

	ensure_instance_type_seeded()
	create_custom_fields(SERVER_SCRIPT_APPROVAL_FIELDS)
	frappe.db.commit()
