"""DMN (Decision Model and Notation) API endpoints.

Provides whitelisted methods for loading and saving DMN XML
per Business Rule Task element within a BPMN Process Model.
"""
import frappe
from frappe import _


@frappe.whitelist()
def get_dmn_xml(process_model: str, decision_id: str) -> str:
	"""Load DMN XML for a specific decision from the child table.

	Args:
		process_model: Name of the BPMN Process Model document.
		decision_id: BPMN element ID of the Business Rule Task.

	Returns:
		The DMN XML string, or empty string if not found.
	"""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("read")

	for row in doc.decision_tables or []:
		if row.decision_id == decision_id:
			return row.dmn_xml or ""

	return ""


@frappe.whitelist(methods=["POST"])
def save_dmn_xml(process_model: str, decision_id: str,
                 decision_name: str, dmn_xml: str) -> dict:
	"""Save or update DMN XML for a specific decision in the child table.

	If a row with the given decision_id already exists, it is updated.
	Otherwise, a new row is appended.

	Uses direct child-row operations to avoid Frappe's HTML sanitiser
	stripping XML content from Code fields during full doc.save().

	Args:
		process_model: Name of the BPMN Process Model document.
		decision_id: BPMN element ID of the Business Rule Task.
		decision_name: Human-readable name of the decision.
		dmn_xml: The DMN 1.3 XML string.

	Returns:
		Dict with success status and the child row name.
	"""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("write")

	if not dmn_xml or not dmn_xml.strip():
		frappe.throw(_("DMN XML cannot be empty"))

	# Find existing row
	existing_row = None
	for row in doc.decision_tables or []:
		if row.decision_id == decision_id:
			existing_row = row
			break

	if existing_row:
		# Direct db_set on the child row — bypasses parent doc validation
		frappe.db.set_value("Workflow Decision Table", existing_row.name, {
			"decision_name": decision_name,
			"dmn_xml": dmn_xml,
		})
	else:
		# Append new row via the parent doc, but skip HTML sanitisation
		doc.flags.skip_editability_check = True
		row = doc.append("decision_tables", {
			"decision_id": decision_id,
			"decision_name": decision_name,
			"dmn_xml": dmn_xml,
		})
		# Save only the new child row directly
		row.db_insert()
		# Update the parent's modified timestamp so version tracking picks it up
		doc.db_set("modified", frappe.utils.now())

	return {"success": True, "decision_id": decision_id}


@frappe.whitelist()
def get_decision_list(process_model: str) -> list:
	"""Get a list of all decisions stored for a process model.

	Returns a lightweight list (without full XML) for populating
	dropdowns in the BPMN properties panel.

	Args:
		process_model: Name of the BPMN Process Model document.

	Returns:
		List of dicts with decision_id and decision_name.
	"""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("read")

	return [
		{
			"decision_id": row.decision_id,
			"decision_name": row.decision_name,
		}
		for row in doc.decision_tables or []
	]
