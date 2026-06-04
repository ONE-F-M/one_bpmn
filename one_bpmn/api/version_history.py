# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def get_diagram_versions(name: str) -> list:
	"""
	Get deployed version history for a BPMN Process Model.

	Returns all sibling models (same process_name) that have been deployed
	(version > 0), ordered by version descending. Excludes the current model
	so the user can pick a different version to compare against.

	Args:
		name: Document name of the BPMN Process Model

	Returns:
		list of version entries with model_name, version, title, deployed info
	"""
	if not name:
		frappe.throw(_("Process Map name is required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	if not doc.process_name:
		return []

	siblings = frappe.get_all(
		"BPMN Process Model",
		filters={
			"process_name": doc.process_name,
			"version": [">", 0],
			"name": ["!=", name],
		},
		fields=["name", "title", "version", "is_active", "deployed_at", "deployed_by", "modified"],
		order_by="version desc",
	)

	result = []
	for s in siblings:
		result.append({
			"model_name": s.name,
			"title": s.title,
			"version": s.version,
			"is_active": s.is_active,
			"deployed_at": s.deployed_at,
			"deployed_by": frappe.utils.get_fullname(s.deployed_by) if s.deployed_by else "",
			"modified": s.modified,
		})

	return result


@frappe.whitelist()
def get_diagram_version_xml(name: str, model_name: str) -> dict:
	"""
	Get the bpmn_xml content from a specific BPMN Process Model version.

	Reads the bpmn_xml directly from the sibling model document.

	Args:
		name: Document name of the current BPMN Process Model (for permission check)
		model_name: Document name of the version to retrieve XML from

	Returns:
		dict with xml_content, model_name, version, title
	"""
	if not name or not model_name:
		frappe.throw(_("Process Map name and model name are required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	version_doc = frappe.get_doc("BPMN Process Model", model_name)
	version_doc.check_permission("read")

	if not version_doc.bpmn_xml:
		frappe.throw(_("No BPMN XML found in version '{0}'").format(model_name))

	return {
		"xml_content": version_doc.bpmn_xml,
		"model_name": model_name,
		"version": version_doc.version,
		"title": version_doc.title,
		"deployed_by": frappe.utils.get_fullname(version_doc.deployed_by) if version_doc.deployed_by else "",
		"deployed_at": version_doc.deployed_at,
	}
