# Copyright (c) 2026, one-fm and contributors
"""Save, import, rename and delete a process map, and retarget Call Activities in other maps."""

import json

from lxml import etree as ET
import frappe
from frappe import _


def save_model(
	model_name: str, xml_content: str, process: str = None, description: str = None
) -> dict:
	"""Save or update a BPMN process model."""
	if not model_name or not xml_content:
		frappe.throw(_("Model name and XML content are required"))

	existing = frappe.db.exists("BPMN Process Model", model_name)

	if existing:
		doc = frappe.get_doc("BPMN Process Model", model_name)
		doc.check_permission("write")
		doc.bpmn_xml = xml_content

		_remove_orphaned_decision_rows(doc, xml_content)

		_sync_decision_names(doc, xml_content)

		if description is not None:
			doc.description = description
		doc.save()

		from processa.api.versions import create_diagram_snapshot

		create_diagram_snapshot(doc.name, xml_content)
	else:
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = model_name
		doc.process_name = process
		doc.bpmn_xml = xml_content
		doc.description = description or ""
		doc.version = 0
		doc.is_active = 0

		doc.check_permission("create")
		from processa.processa_engine.doctype.bpmn_process_model.bpmn_process_model import new_process_id

		doc.process_id = new_process_id(process or model_name)
		doc.flags.skip_process_id_regeneration = True
		doc.insert()

		from processa.api.versions import create_diagram_snapshot

		create_diagram_snapshot(doc.name, xml_content)

	return {"name": doc.name, "model_name": doc.title, "version": doc.version, "is_active": doc.is_active}


def _remove_orphaned_decision_rows(doc, xml_content: str):
	"""Remove child rows in decision_tables whose element is not in the XML."""
	if not doc.decision_tables:
		return

	import re

	id_matches = re.findall(r"""\bid=(?:\"([^\"]+)\"|'([^']+)')""", xml_content)
	element_ids = {m[0] or m[1] for m in id_matches}

	doc.decision_tables = [row for row in doc.decision_tables if row.decision_id in element_ids]


def _sync_decision_names(doc, xml_content: str):
	"""Sync decision_name fields from Business Rule Task element names."""
	if not doc.decision_tables:
		return

	import re

	pattern = re.compile(
		r'<(?:[\w-]+:)?businessRuleTask\s+([^>]*?)(?:/>|>)',
		re.IGNORECASE | re.DOTALL
	)

	element_names = {}
	for match in pattern.finditer(xml_content):
		attrs = match.group(1)
		id_match = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
		if not id_match:
			continue
		element_id = id_match.group(1)
		name_match = re.search(r'\bname=["\']([^"\']*)["\']', attrs)
		element_name = name_match.group(1) if name_match else element_id
		element_names[element_id] = element_name

	for row in doc.decision_tables:
		new_name = element_names.get(row.decision_id)
		if new_name and new_name != row.decision_name:
			row.decision_name = new_name


def import_model(
	xml_content: str,
	title: str = None,
	process: str = None,
) -> dict:
	"""Import a BPMN XML string as a new or updated BPMN Process Model."""
	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	# Bytes, because lxml rejects a str that carries an encoding declaration.
	try:
		parser = ET.XMLParser(resolve_entities=False, no_network=True)
		root = ET.fromstring(xml_content.strip().encode("utf-8"), parser=parser)
	except ET.XMLSyntaxError as exc:
		frappe.throw(_("Invalid BPMN XML: {0}").format(str(exc)))

	bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	process_el = root.find(f"{{{bpmn_ns}}}process")
	if process_el is None:
		process_el = root.find("process")

	if process_el is None:
		frappe.throw(
			_("Invalid BPMN XML: no <bpmn:process> element found. Please upload a valid BPMN 2.0 file.")
		)

	extracted_process_id = process_el.get("id")
	if not extracted_process_id:
		frappe.throw(_("Invalid BPMN XML: <bpmn:process> element has no 'id' attribute"))

	effective_title = title or process_el.get("name") or extracted_process_id

	existing_name = frappe.db.get_value("BPMN Process Model", {"process_id": extracted_process_id}, "name")

	if existing_name:
		doc = frappe.get_doc("BPMN Process Model", existing_name)
		doc.check_permission("write")
		doc.bpmn_xml = xml_content
		if process:
			doc.process_name = process
		if effective_title:
			doc.title = effective_title
		# Import is allowed on a Production site too.
		doc.flags.skip_editability_check = True
		doc.save()

		if effective_title and effective_title != doc.name:
			try:
				frappe.rename_doc(
					"BPMN Process Model",
					doc.name,
					effective_title,
					force=True,
					merge=False,
				)
				doc = frappe.get_doc("BPMN Process Model", effective_title)
			except Exception:
				pass  # a duplicate title keeps the existing name

		action = "updated"
	else:
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = effective_title
		doc.process_id = extracted_process_id
		doc.bpmn_xml = xml_content
		doc.process_name = process or None
		doc.version = 0
		doc.check_permission("create")
		doc.flags.skip_editability_check = True
		doc.flags.skip_process_id_regeneration = True
		doc.insert()
		action = "created"

	# Recompile so the spec matches the running code; a failed compile still keeps the import.
	compile_result = {}
	try:
		from processa.api.deploy import compile_process_model

		compile_result = compile_process_model(doc.name) or {}
	except Exception:
		frappe.log_error(
			title=f"BPMN import: could not compile {doc.name}",
			message=frappe.get_traceback(),
		)

	return {
		"name": doc.name,
		"model_name": doc.title,
		"process_id": doc.process_id,
		"action": action,
		"compiled": bool(compile_result.get("success")),
		"warnings": compile_result.get("warnings") or [],
	}


def retarget_call_activities(references: str) -> dict:
	"""Batch-update Call Activity ``calledElement`` attributes in BPMN models."""
	import xml.etree.ElementTree as _ET

	refs = json.loads(references) if isinstance(references, str) else references
	if not refs:
		return {"success": True, "updated": 0}

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	# Registered so the rewritten XML keeps its prefixes instead of ns0 and ns1.
	_ET.register_namespace("bpmn", BPMN_NS)
	_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
	_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
	_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
	_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

	updated = 0
	by_model = {}
	for ref in refs:
		model_name = ref.get("source_model")
		if model_name:
			by_model.setdefault(model_name, []).append(ref)

	for model_name, model_refs in by_model.items():
		if not frappe.db.exists("BPMN Process Model", model_name):
			continue

		doc = frappe.get_doc("BPMN Process Model", model_name)
		doc.check_permission("write")

		if not doc.bpmn_xml:
			continue

		try:
			root = _ET.fromstring(doc.bpmn_xml.strip().encode("utf-8"))
		except Exception:
			frappe.log_error(
				title="BPMN: update_call_activity_references XML parse failed",
				message=f"Failed to parse XML for model '{model_name}'",
			)
			continue

		xml_changed = False
		for ref in model_refs:
			element_id = ref.get("source_element_id", "")
			old_pid = ref.get("old_process_id", "")
			new_pid = ref.get("new_process_id", "")

			if not element_id or not old_pid or not new_pid:
				continue

			for call_activity in root.iter(f"{{{BPMN_NS}}}callActivity"):
				if (
					call_activity.get("id") == element_id
					and call_activity.get("calledElement", "").strip() == old_pid
				):
					call_activity.set("calledElement", new_pid)
					xml_changed = True
					updated += 1
					break

		if xml_changed:
			doc.bpmn_xml = _ET.tostring(root, encoding="unicode", xml_declaration=False)
			doc.flags.skip_editability_check = True
			doc.save(ignore_permissions=True)  # write permission on this model was checked above

	return {"success": True, "updated": updated}


def delete_model(name: str) -> dict:
	"""Delete a BPMN process model diagram."""

	if not name:
		frappe.throw(_("Process Map name is required"))

	from processa.api.canvas_comments import cleanup_process_model_assets
	cleanup_process_model_assets(name)

	# The model's on_trash removes its diagram snapshots first, so the link check passes.
	frappe.delete_doc("BPMN Process Model", name)

	return {"success": True}


def rename_model(name: str, new_title: str) -> dict:
	"""Rename a BPMN Process Model - fast path."""
	if not name or not new_title:
		frappe.throw(_("Current name and new title are required"))

	new_title = new_title.strip()
	if not new_title:
		frappe.throw(_("New title cannot be empty"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("write")

	current_title = doc.title
	if new_title == current_title:
		return {"name": name, "model_name": current_title}

	global_duplicate = frappe.db.get_value(
		"BPMN Process Model",
		{"title": new_title, "name": ("!=", name)},
		"name",
	)
	if global_duplicate:
		frappe.throw(
			_("A BPMN Process Model with the title '{0}' already exists").format(new_title),
			frappe.ValidationError,
		)

	# Sets the title without save() to skip the validate hooks.
	frappe.db.set_value("BPMN Process Model", name, "title", new_title, update_modified=True)

	new_name = name
	if new_title != name:
		try:
			actual_new_name = frappe.rename_doc(
				"BPMN Process Model",
				name,
				new_title,
				force=True,
				merge=False,
			)
			new_name = actual_new_name or new_title
		except frappe.ValidationError:
			frappe.log_error(
				title="BPMN Process Model rename failed",
				message=f"Could not rename '{name}' to '{new_title}'",
			)
			frappe.throw(_("A process model with the name '{0}' already exists").format(new_title))

	return {
		"name": new_name,
		"model_name": new_title,
	}

