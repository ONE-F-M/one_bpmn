import frappe


def after_install():
	"""Post-install setup for a fresh one_bpmn install.

	Patches are marked complete (not run) on install, so anything a patch
	seeds has to be seeded here as well.
	"""
	from one_bpmn.api.editability import ensure_instance_type_seeded

	ensure_instance_type_seeded()
	frappe.db.commit()
