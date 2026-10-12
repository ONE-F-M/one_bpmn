import frappe


def execute():
	"""Backfill Processa Settings → Instance Type on existing sites.

	The field ships with a "Local" default, but Frappe does not write a Single
	field's default onto an existing ``tabSingles`` row — so without this the
	setting reads as unset everywhere and every Instance Type gate (production
	lock, Reassign User Task, Review Doctypes/Workflow Objects) sits idle.

	The value is derived from the pre-Instance-Type signals so behaviour is
	preserved across the upgrade. See
	``one_bpmn.api.editability.ensure_instance_type_seeded``.
	"""
	from one_bpmn.api.editability import ensure_instance_type_seeded

	frappe.reload_doc("one_bpmn", "doctype", "processa_settings")
	instance_type = ensure_instance_type_seeded()
	print(f"Processa Settings → Instance Type: {instance_type}")
