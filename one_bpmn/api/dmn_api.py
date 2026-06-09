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
def get_decision_list(process_model: str, search_term: str = None) -> list:
	"""Get a list of all decisions stored for a process model.

	Returns a lightweight list (without full XML) for populating
	dropdowns in the BPMN properties panel.

	Args:
		process_model: Name of the BPMN Process Model document.
		search_term: Optional search string to filter by decision_id
		             or decision_name (case-insensitive LIKE match).

	Returns:
		List of dicts with decision_id and decision_name.
	"""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("read")

	results = []
	for row in doc.decision_tables or []:
		if search_term:
			term = search_term.lower()
			id_match = term in (row.decision_id or "").lower()
			name_match = term in (row.decision_name or "").lower()
			if not id_match and not name_match:
				continue
		results.append({
			"decision_id": row.decision_id,
			"decision_name": row.decision_name,
		})

	return results


@frappe.whitelist(methods=["POST"])
def update_decision_name(process_model: str, decision_id: str,
                         decision_name: str) -> dict:
	"""Update only the decision_name for an existing decision table row.

	Used when a Business Rule Task is renamed after its DMN XML has
	already been saved. Syncs the human-readable name without touching
	the DMN XML content.

	Args:
		process_model: Name of the BPMN Process Model document.
		decision_id: BPMN element ID of the Business Rule Task.
		decision_name: New human-readable name for the decision.

	Returns:
		Dict with success status.
	"""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("write")

	for row in doc.decision_tables or []:
		if row.decision_id == decision_id:
			if row.decision_name != decision_name:
				frappe.db.set_value("Workflow Decision Table", row.name, {
					"decision_name": decision_name,
				})
			return {"success": True, "decision_id": decision_id}

	return {"success": False, "message": _("Decision row not found")}
