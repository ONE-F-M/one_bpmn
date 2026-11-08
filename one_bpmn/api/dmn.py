"""DMN decision table endpoints, one table per Business Rule Task in a BPMN Process Model."""

import frappe
from frappe import _


@frappe.whitelist()
def get_dmn_xml(process_model: str, decision_id: str) -> str:
	"""Return the DMN XML for one decision, or an empty string if there is none."""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("read")

	for row in doc.decision_tables or []:
		if row.decision_id == decision_id:
			return row.dmn_xml or ""

	return ""


@frappe.whitelist(methods=["POST"])
def save_dmn_xml(process_model: str, decision_id: str,
                 decision_name: str, dmn_xml: str) -> dict:
	"""Update the decision's row or append a new one.

	Writes the child row directly so a full doc.save() does not sanitise the XML in the Code field.
	"""
	doc = frappe.get_doc("BPMN Process Model", process_model)
	doc.check_permission("write")

	if not dmn_xml or not dmn_xml.strip():
		frappe.throw(_("DMN XML cannot be empty"))

	existing_row = None
	for row in doc.decision_tables or []:
		if row.decision_id == decision_id:
			existing_row = row
			break

	if existing_row:
		# Bypasses parent doc validation
		frappe.db.set_value("Workflow Decision Table", existing_row.name, {
			"decision_name": decision_name,
			"dmn_xml": dmn_xml,
		})
	else:
		doc.flags.skip_editability_check = True
		row = doc.append("decision_tables", {
			"decision_id": decision_id,
			"decision_name": decision_name,
			"dmn_xml": dmn_xml,
		})
		row.db_insert()
		# Bump the parent's modified so version tracking picks up the change
		doc.db_set("modified", frappe.utils.now())

	return {"success": True, "decision_id": decision_id}


@frappe.whitelist()
def get_decision_list(process_model: str, search_term: str = None) -> list:
	"""Return decision_id and decision_name of each stored decision, without the XML.

	search_term filters case-insensitively on either field.
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
