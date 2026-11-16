import frappe


def execute():
	"""Set all existing BPMN Process Models to inactive.

	Activation should only happen when a model is explicitly deployed
	to production. The old default was is_active=1, so all existing
	models need to be reset to inactive.
	"""
	frappe.db.set_value(
		"BPMN Process Model",
		{"is_active": 1},
		"is_active",
		0,
		update_modified=False,
	)
