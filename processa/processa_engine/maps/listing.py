# Copyright (c) 2026, one-fm and contributors
"""Read process maps and Process records for the editor and the process list."""

from lxml import etree as ET
import frappe
from frappe import _


def model_details(name: str) -> dict:
	"""Get a process model by name."""
	if not name:
		frappe.throw(_("Model name is required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	xml_content = doc.bpmn_xml
	if xml_content:
		xml_content = _sanitize_html_attrs_for_viewer(xml_content)

	return {
		"name": doc.name,
		"model_name": doc.title,
		"title": doc.title,
		"process_id": doc.process_id,
		"process_name": doc.process_name,
		"description": doc.description,
		"xml_content": xml_content,
		"bpmn_xml": xml_content,
		"version": doc.version,
		"is_active": doc.is_active,
		"modified": doc.modified,
		"owner": doc.owner,
	}


def _sanitize_html_attrs_for_viewer(bpmn_xml: str) -> str:
	"""Encode raw HTML in spiffworkflow:* attributes to base64."""
	import base64 as _b64

	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
	_HTML_ATTRS = (
		f"{{{SPIFF_NS}}}notifyAssigneeBody",
		f"{{{SPIFF_NS}}}emailBody",
	)

	try:
		parser = ET.XMLParser(resolve_entities=False, no_network=True)
		root = ET.fromstring(bpmn_xml.strip().encode("utf-8"), parser=parser)

		changed = False
		for attr_key in _HTML_ATTRS:
			for elem in root.iter():
				raw = elem.get(attr_key)
				if not raw:
					continue
				try:
					_b64.b64decode(raw).decode("utf-8")
					continue  # valid base64 - skip
				except Exception:
					pass
				encoded = _b64.b64encode(raw.encode("utf-8")).decode("ascii")
				elem.set(attr_key, encoded)
				changed = True

		if not changed:
			return bpmn_xml

		return ET.tostring(root, encoding="unicode", xml_declaration=False)
	except Exception:
		return bpmn_xml


def find_model_by_process_id(process_id: str) -> dict:
	"""Resolve a process_id to the BPMN Process Model that owns it."""
	if not process_id:
		return {}

	result = frappe.db.get_value(
		"BPMN Process Model",
		filters={"process_id": process_id},
		fieldname=["name", "title", "process_name", "process_id"],
		as_dict=True,
	)
	return result or {}


def processes_with_status() -> list:
	"""List all Process records that have BPMN diagrams or are accessible for creating diagrams."""
	processes = frappe.get_list(
		"Process",
		fields=[
			"name",
			"process_name",
			"process_owner",
			"process_owner_name",
			"description",
			"modified",
			"creation",
		],
		order_by="modified desc",
	)

	diagram_counts = frappe.get_all(
		"BPMN Process Model", fields=["process_name", "count(*) as count"], group_by="process_name"
	)
	count_map = {d["process_name"]: d["count"] for d in diagram_counts}

	for proc in processes:
		proc["diagram_count"] = count_map.get(proc["name"], 0)

		active_model = frappe.db.get_value(
			"BPMN Process Model",
			filters={"process_name": proc["name"], "is_active": 1},
			fieldname=["name", "modified", "process_id"],
			as_dict=True,
		)
		proc["active_process_id"] = active_model.process_id if active_model else None

		if active_model:
			proc["status"] = "Active"
			proc["last_modified"] = active_model["modified"]
		elif proc["diagram_count"] > 0:
			latest = frappe.db.get_value(
				"BPMN Process Model",
				filters={"process_name": proc["name"]},
				fieldname="modified",
				order_by="modified desc",
			)
			proc["status"] = "Inactive"
			proc["last_modified"] = latest or proc["modified"]
		else:
			proc["status"] = "No Process Maps"
			proc["last_modified"] = proc["modified"]

	return processes


def process_diagrams(process: str) -> dict:
	"""Get all diagrams for a specific process."""
	if not process:
		frappe.throw(_("Process name is required"))

	proc = frappe.get_doc("Process", process)
	proc.check_permission("read")

	diagrams = frappe.get_list(
		"BPMN Process Model",
		filters={"process_name": process},
		fields=[
			"name",
			"title",
			"process_id",
			"description",
			"version",
			"is_active",
			"modified",
			"modified_by",
			"process_implementation",
		],
		order_by="is_active desc, modified desc",
	)

	from processa.api.editability import annotate_model_editability

	annotate_model_editability(diagrams)

	user_emails = list({d["modified_by"] for d in diagrams if d.get("modified_by")})
	user_names = {}
	if user_emails:
		for row in frappe.get_all("User", filters={"name": ["in", user_emails]}, fields=["name", "full_name"]):
			user_names[row["name"]] = row["full_name"]

	for d in diagrams:
		d["model_name"] = d["title"]
		d["modified_by_name"] = user_names.get(d.get("modified_by"), d.get("modified_by", ""))

	return {
		"name": proc.name,
		"process_name": proc.process_name,
		"process_owner": proc.process_owner,
		"process_owner_name": proc.process_owner_name,
		"description": proc.description,
		"diagrams": diagrams,
	}

