import frappe


def execute():
	"""Drop the BPMN runs that were started against a Pathfinder Log."""
	instances = frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "Pathfinder Log"},
		pluck="name",
	)
	if not instances:
		return

	frappe.db.delete("BPMN Activity Log", {"instance": ["in", instances]})
	frappe.db.delete("BPMN Process Instance", {"name": ["in", instances]})
