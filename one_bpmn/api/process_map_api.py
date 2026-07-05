# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

from lxml import etree as ET
import frappe
from frappe import _
from frappe.utils import cint


# ============================================
# HTML attribute sanitization for BPMN viewer
# ============================================

def _sanitize_html_attrs_for_viewer(bpmn_xml: str) -> str:
	"""Encode raw HTML in spiffworkflow:* attributes to base64.

	Existing BPMN XML may contain raw HTML (e.g. ``<p>Hello</p>``) in
	attributes like ``notifyAssigneeBody`` and ``emailBody``.  The BPMN
	viewer's XML parser chokes on these because ``</p>`` looks like a
	closing XML tag.

	This function encodes any raw HTML attribute values to base64 before
	the XML reaches the frontend.  Already-encoded (base64) values are
	left untouched.  Falls back to the original XML on any error.
	"""
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
				# Already base64?
				try:
					_b64.b64decode(raw).decode("utf-8")
					continue  # valid base64 — skip
				except Exception:
					pass
				# Raw HTML — encode to base64
				encoded = _b64.b64encode(raw.encode("utf-8")).decode("ascii")
				elem.set(attr_key, encoded)
				changed = True

		if not changed:
			return bpmn_xml

		return ET.tostring(root, encoding="unicode", xml_declaration=False)
	except Exception:
		return bpmn_xml


# ============================================
# Process Model CRUD API
# ============================================


@frappe.whitelist()
def save_process_model(
	model_name: str, xml_content: str, process: str = None, description: str = None
) -> dict:
	"""
	Save or update a BPMN process model.

	Args:
		model_name: Name / title of the process model (maps to 'title' field)
		xml_content: BPMN XML content (maps to 'bpmn_xml' field)
		process: Legacy param (ignored — kept for frontend compat)
		description: Optional description

	Returns:
		dict with name and version of saved model
	"""
	if not model_name or not xml_content:
		frappe.throw(_("Model name and XML content are required"))

	# Check if model exists (title is the autoname)
	existing = frappe.db.exists("BPMN Process Model", model_name)

	if existing:
		# Update existing model
		doc = frappe.get_doc("BPMN Process Model", model_name)
		doc.check_permission("write")
		doc.bpmn_xml = xml_content

		# Clean up orphaned decision table rows whose Business Rule Task
		# element no longer exists in the updated BPMN XML.
		_remove_orphaned_decision_rows(doc, xml_content)

		# Sync decision_name from BPMN element names so that renaming
		# a task after DMN XML was saved updates the child row.
		_sync_decision_names(doc, xml_content)

		if description is not None:
			doc.description = description
		doc.save()

		# Record a full-XML snapshot for the version history panel.
		from one_bpmn.api.version_history import create_diagram_snapshot

		create_diagram_snapshot(doc.name, xml_content)
	else:
		# Create new model
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = model_name
		doc.process_name = process
		doc.bpmn_xml = xml_content
		doc.description = description or ""
		doc.version = 0
		doc.is_active = 0

		doc.check_permission("create")
		# The caller (Processa editor or handleDuplicateTab) already
		# embeds a unique process_id in the XML — skip re-generation.
		doc.flags.skip_process_id_regeneration = True
		doc.insert()

		# Seed the version history with the initial snapshot.
		from one_bpmn.api.version_history import create_diagram_snapshot

		create_diagram_snapshot(doc.name, xml_content)

	return {"name": doc.name, "model_name": doc.title, "version": doc.version, "is_active": doc.is_active}


@frappe.whitelist()
def create_map_from_version(
	process: str, model_name: str, base_version: str, description: str = None
) -> dict:
	"""Create a new process map seeded from a named version snapshot.

	Used by the editor "+" flow once a process already has at least one process
	map: instead of starting blank, the new map is built on top of a chosen
	*named* version from the active map's history, which serves as the base
	template the user builds from.

	The new map receives a fresh, unique process_id — the BPMN Process Model
	controller regenerates it on insert (and rewrites the XML references) because
	the seeded XML still carries the source map's process_id — so the new map has
	its own identity and does not collide with the source.

	Args:
		process: Name of the parent Process.
		model_name: Title for the new process map. Must be unique.
		base_version: Document name of the BPMN Diagram Version to seed from.
			Must be a *named* version.
		description: Optional description.

	Returns:
		dict with name, model_name, version, is_active of the created map.
	"""
	if not process or not model_name or not base_version:
		frappe.throw(_("Process, name and base version are required"))

	title = model_name.strip()
	if not title:
		frappe.throw(_("Name is required"))

	# Enforce a unique name (BPMN Process Model autoname is field:title, so the
	# document name equals the title). Reject duplicates with a friendly message.
	if frappe.db.exists("BPMN Process Model", title):
		frappe.throw(
			_("A process map named '{0}' already exists. Please choose a different name.").format(title)
		)

	snap = frappe.get_doc("BPMN Diagram Version", base_version)
	if not snap.is_named:
		frappe.throw(_("The base version must be a named version"))
	if not snap.bpmn_xml:
		frappe.throw(_("The selected base version has no diagram content"))

	# Permission is gated on the source process model the snapshot belongs to.
	frappe.get_doc("BPMN Process Model", snap.model).check_permission("read")

	doc = frappe.new_doc("BPMN Process Model")
	doc.title = title
	doc.process_name = process
	doc.bpmn_xml = snap.bpmn_xml
	doc.description = description or ""
	doc.version = 0
	doc.is_active = 0

	doc.check_permission("create")
	# Intentionally do NOT set skip_process_id_regeneration: the seeded XML
	# carries the source map's process_id, so let the controller mint a fresh
	# unique one to avoid identity collisions during import/deploy.
	doc.insert()

	# Seed the new map's version history with its initial snapshot.
	from one_bpmn.api.version_history import create_diagram_snapshot

	create_diagram_snapshot(doc.name, doc.bpmn_xml)

	return {"name": doc.name, "model_name": doc.title, "version": doc.version, "is_active": doc.is_active}


def _remove_orphaned_decision_rows(doc, xml_content: str):
	"""Remove child rows in decision_tables whose element no longer exists.

	When a Business Rule Task is replaced with another element type in the
	BPMN modeler, the element ID disappears from the XML but the DMN child
	row persists in the database.  This helper scans the BPMN XML for all
	element IDs and drops any child rows that are no longer referenced.

	Operates on the in-memory doc before save — no direct DB mutations.
	"""
	if not doc.decision_tables:
		return

	# Collect all element IDs present in the BPMN XML.
	# We do a broad search for id="..." attributes so that we catch any
	# element type (not only businessRuleTask) — this is intentional to
	# avoid false positives if the ID is reused on a different element.
	import re

	id_matches = re.findall(r"""\bid=(?:\"([^\"]+)\"|'([^']+)')""", xml_content)
	element_ids = {m[0] or m[1] for m in id_matches}

	doc.decision_tables = [row for row in doc.decision_tables if row.decision_id in element_ids]


def _sync_decision_names(doc, xml_content: str):
	"""Sync decision_name fields from Business Rule Task element names.

	When a user renames a Business Rule Task in the BPMN modeler after
	its DMN XML has already been saved, the decision_name in the child
	table becomes stale.  This helper extracts all businessRuleTask
	element names from the BPMN XML and updates matching child rows.

	Operates on the in-memory doc before save — no direct DB mutations.
	"""
	if not doc.decision_tables:
		return

	# Parse the BPMN XML to extract businessRuleTask elements.
	# Use a namespace-aware approach to handle both prefixed and bare tags.
	import re

	# Match <bpmn:businessRuleTask ...> or <businessRuleTask ...>
	# Capture the full attributes block so we can extract id and name.
	pattern = re.compile(
		r'<(?:[\w-]+:)?businessRuleTask\s+([^>]*?)(?:/>|>)',
		re.IGNORECASE | re.DOTALL
	)

	# Build a map of element_id → element_name from the XML
	element_names = {}
	for match in pattern.finditer(xml_content):
		attrs = match.group(1)
		# Extract id attribute
		id_match = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
		if not id_match:
			continue
		element_id = id_match.group(1)
		# Extract name attribute (may not exist)
		name_match = re.search(r'\bname=["\']([^"\']*)["\']', attrs)
		element_name = name_match.group(1) if name_match else element_id
		element_names[element_id] = element_name

	# Update child rows where the name has changed
	for row in doc.decision_tables:
		new_name = element_names.get(row.decision_id)
		if new_name and new_name != row.decision_name:
			row.decision_name = new_name


@frappe.whitelist()
def import_bpmn(
	xml_content: str,
	title: str = None,
	process: str = None,
) -> dict:
	"""
	Import a BPMN XML string as a new or updated BPMN Process Model.

	The process_id is extracted from the first <bpmn:process id="…"> element in
	the XML. If a BPMN Process Model with that process_id already exists it is
	updated; otherwise a new record is created.

	Args:
		xml_content: Raw BPMN XML text (content of a .bpmn file)
		title:       Optional human-readable title. Defaults to the process_id.
		process:     Optional link to a Process DocType record.

	Returns:
		dict with name, model_name, process_id, and action ('created'|'updated')
	"""
	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	# --- Validate & parse XML ---
	# lxml raises TypeError when fromstring() receives a str containing an encoding
	# declaration (<?xml ... encoding="UTF-8"?>). Encoding to bytes avoids this.
	# Use a hardened parser to prevent XXE / entity-expansion attacks.
	try:
		parser = ET.XMLParser(resolve_entities=False, no_network=True)
		root = ET.fromstring(xml_content.strip().encode("utf-8"), parser=parser)
	except ET.XMLSyntaxError as exc:
		frappe.throw(_("Invalid BPMN XML: {0}").format(str(exc)))

	# Register namespaces so ElementTree can search them
	bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	# Accept both namespaced and bare <process> tags
	process_el = root.find(f"{{{bpmn_ns}}}process")
	if process_el is None:
		# Fallback: look without namespace (some exporters omit it)
		process_el = root.find("process")

	if process_el is None:
		frappe.throw(
			_("Invalid BPMN XML: no <bpmn:process> element found. Please upload a valid BPMN 2.0 file.")
		)

	extracted_process_id = process_el.get("id")
	if not extracted_process_id:
		frappe.throw(_("Invalid BPMN XML: <bpmn:process> element has no 'id' attribute"))

	effective_title = title or process_el.get("name") or extracted_process_id

	# --- Upsert logic: match by process_id (unique field) ---
	existing_name = frappe.db.get_value("BPMN Process Model", {"process_id": extracted_process_id}, "name")

	if existing_name:
		doc = frappe.get_doc("BPMN Process Model", existing_name)
		doc.check_permission("write")
		doc.bpmn_xml = xml_content
		if process:
			doc.process_name = process
		# Always sync the title field so the return value is accurate
		if effective_title:
			doc.title = effective_title
		# Import is allowed even on Production — bypass editability gate
		doc.flags.skip_editability_check = True
		doc.save()

		# Rename the document if the human title has changed
		# (autoname only runs on insert, so we must rename manually)
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
				# If rename fails (e.g. duplicate title), keep existing name
				pass

		action = "updated"
	else:
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = effective_title
		doc.process_id = extracted_process_id
		doc.bpmn_xml = xml_content
		doc.process_name = process or None
		doc.version = 0
		doc.check_permission("create")
		# Import is allowed even on Production — bypass editability gate
		doc.flags.skip_editability_check = True
		# Preserve the original process_id from the imported file
		doc.flags.skip_process_id_regeneration = True
		doc.insert()
		action = "created"

	return {
		"name": doc.name,
		"model_name": doc.title,
		"process_id": doc.process_id,
		"action": action,
	}


def _extract_bpmn_references(xml_content: str) -> dict:
	"""
	Parse BPMN XML and extract all external references.

	Shared helper used by both ``validate_bpmn_readiness()`` and
	``config_export_import.export_bpmn_config()``.

	Args:
		xml_content: Raw BPMN XML text (must be non-empty, already validated)

	Returns:
		dict with keys: doctypes, fields, workflow_states, workflow_actions,
		server_scripts, lane_roles, apply_workflow_doctypes, root, process_el
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(xml_content.strip().encode("utf-8"))
	except Exception as exc:
		frappe.throw(_("Invalid BPMN XML: {0}").format(str(exc)))

	# DocTypes: collected from all sources
	referenced_doctypes = set()

	# Fields: list of (doctype, fieldname) tuples
	referenced_fields = []

	# Workflow States
	referenced_states = set()

	# Workflow Action Master labels (from user task actions)
	referenced_actions = set()

	# DocTypes that use apply_workflow (need workflow_state field)
	apply_workflow_doctypes = set()

	# Server Script names (from script tasks)
	referenced_scripts = set()

	# Lane roles (from lane name attributes)
	referenced_lane_roles = set()

	# ── Parse Start Events ────────────────────────────────────────────────
	for start_event in root.iter(f"{{{BPMN_NS}}}startEvent"):
		dt = start_event.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		if dt:
			referenced_doctypes.add(dt)

		ws = start_event.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		if ws:
			referenced_states.add(ws)

		# Also check conditional definition children
		cond_def = start_event.find(f"{{{BPMN_NS}}}conditionalEventDefinition")
		if cond_def is not None:
			dt2 = cond_def.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
			if dt2:
				referenced_doctypes.add(dt2)
			ws2 = cond_def.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
			if ws2:
				referenced_states.add(ws2)

	# ── Parse Service Tasks ───────────────────────────────────────────────
	for service_task in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		attrs = {}
		for attr_name, attr_value in service_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}"):]
				attrs[key] = attr_value

		service_type = attrs.get("serviceType", "")

		if service_type == "apply_workflow":
			target_dt = attrs.get("serviceTargetDoctype", "")
			if target_dt:
				referenced_doctypes.add(target_dt)
				apply_workflow_doctypes.add(target_dt)

			state = attrs.get("workflowState", "")
			if state:
				referenced_states.add(state)

		elif service_type == "update_field":
			target_dt = attrs.get("updateFieldDoctype", "")
			if target_dt:
				referenced_doctypes.add(target_dt)

			rows_json = attrs.get("updateFieldRows", "")
			if rows_json:
				try:
					rows = json.loads(rows_json)
					for row in rows:
						field = row.get("field", "")
						if field and target_dt:
							referenced_fields.append((target_dt, field))
				except (json.JSONDecodeError, ValueError):
					pass

			legacy_field = attrs.get("updateFieldName", "")
			if legacy_field and target_dt:
				referenced_fields.append((target_dt, legacy_field))

		else:
			target_dt = attrs.get("serviceTargetDoctype", "")
			if target_dt:
				referenced_doctypes.add(target_dt)

	# ── Parse User Tasks ──────────────────────────────────────────────────
	for user_task in root.iter(f"{{{BPMN_NS}}}userTask"):
		attrs = {}
		for attr_name, attr_value in user_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}"):]
				attrs[key] = attr_value

		target_dt = attrs.get("targetDoctype", "")
		if target_dt:
			referenced_doctypes.add(target_dt)

		assignee_field = attrs.get("assigneeDocfield", "")
		if assignee_field and target_dt:
			referenced_fields.append((target_dt, assignee_field))

		actions_json = attrs.get("taskActions", "")
		if actions_json:
			try:
				actions = json.loads(actions_json)
				for action in actions:
					label = action.get("action", "")
					if label:
						referenced_actions.add(label)
			except (json.JSONDecodeError, ValueError):
				pass

	# ── Parse Script Tasks ────────────────────────────────────────────────
	for script_task in root.iter(f"{{{BPMN_NS}}}scriptTask"):
		script_name = script_task.get(f"{{{SPIFF_NS}}}serverScript", "")
		if script_name:
			referenced_scripts.add(script_name)

	# ── Parse Lane Roles ──────────────────────────────────────────────────
	for lane in root.iter(f"{{{BPMN_NS}}}lane"):
		role_name = lane.get("name", "").strip()
		if role_name:
			referenced_lane_roles.add(role_name)

	# ── Extract email doc-fields from send_email service tasks ────────────
	for service_task in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		attrs = {}
		for attr_name, attr_value in service_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}"):]
				attrs[key] = attr_value

		if attrs.get("serviceType") == "send_email":
			email_dt = attrs.get("emailDoctype", "")
			if email_dt:
				to_fields = attrs.get("emailToDocFields", "")
				for field in to_fields.split(","):
					field = field.strip()
					if field:
						referenced_fields.append((email_dt, field))

				cc_fields = attrs.get("emailCcDocFields", "")
				for field in cc_fields.split(","):
					field = field.strip()
					if field:
						referenced_fields.append((email_dt, field))

	# ── workflow_state field check for apply_workflow doctypes ─────────────
	for dt in apply_workflow_doctypes:
		referenced_fields.append((dt, "workflow_state"))

	# ── Extract Call Activity references ─────────────────────────────────
	call_activities = _extract_call_activity_refs(xml_content)

	# ── Extract process-level attributes ─────────────────────────────────
	_process_el = root.find(f"{{{BPMN_NS}}}process") or root.find("process")

	return {
		"doctypes": referenced_doctypes,
		"fields": referenced_fields,
		"workflow_states": referenced_states,
		"workflow_actions": referenced_actions,
		"server_scripts": referenced_scripts,
		"lane_roles": referenced_lane_roles,
		"apply_workflow_doctypes": apply_workflow_doctypes,
		"call_activities": call_activities,
		"root": root,
		"process_el": _process_el,
	}


def _extract_call_activity_refs(xml_content: str) -> list:
	"""
	Parse BPMN XML and extract all Call Activity references.

	Each Call Activity has a ``calledElement`` attribute that stores the
	process_id of the target process model.

	Args:
		xml_content: Raw BPMN XML text

	Returns:
		list of dicts with keys: bpmn_id, called_element, name
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not xml_content or not xml_content.strip():
		return []

	try:
		root = _ET.fromstring(
			xml_content.strip().encode("utf-8") if isinstance(xml_content, str) else xml_content
		)
	except Exception:
		return []

	refs = []
	for call_activity in root.iter(f"{{{BPMN_NS}}}callActivity"):
		bpmn_id = call_activity.get("id", "")
		called_element = call_activity.get("calledElement", "").strip()
		name = call_activity.get("name", "").strip()
		if bpmn_id and called_element:
			refs.append({
				"bpmn_id": bpmn_id,
				"called_element": called_element,
				"name": name or bpmn_id,
			})

	return refs


def _check_call_activity_references(model_name: str) -> list:
	"""
	Detect Call Activities in other models that reference process models
	which will be disabled when ``model_name`` is deployed.

	When a model is deployed, all sibling models (same ``process_name``,
	different ``name``) that are currently active are deactivated.  If any
	other active model (across all processes) has a Call Activity whose
	``calledElement`` points to one of those siblings' ``process_id``
	values, the reference will break at runtime.

	This function scans all active models (excluding the model being
	deployed and its siblings) for such references and returns a list
	of flagged items suitable for the readiness checklist.

	Args:
		model_name: The name of the BPMN Process Model being deployed.

	Returns:
		list of item dicts with type ``call_activity_ref`` for the
		readiness checklist categories.
	"""
	model = frappe.db.get_value(
		"BPMN Process Model",
		model_name,
		["name", "process_name", "process_id"],
		as_dict=True,
	)
	if not model or not model.process_name:
		return []

	# Find sibling models that will be disabled by this deployment
	# (same process_name, currently active, not the model being deployed)
	siblings = frappe.get_all(
		"BPMN Process Model",
		filters={
			"process_name": model.process_name,
			"is_active": 1,
			"name": ["!=", model_name],
		},
		fields=["name", "process_id", "title"],
	)
	if not siblings:
		return []

	# Build a map: process_id → sibling info (for the models being disabled)
	disabled_process_ids = {}
	for s in siblings:
		if s.process_id:
			disabled_process_ids[s.process_id] = s

	if not disabled_process_ids:
		return []

	# Scan all other active models for Call Activities referencing the
	# about-to-be-disabled process_ids.
	# Exclude the model being deployed AND its siblings (they are the ones
	# being disabled — not interested in self-references).
	sibling_names = [s.name for s in siblings] + [model_name]
	other_models = frappe.get_all(
		"BPMN Process Model",
		filters={
			"name": ["not in", sibling_names],
			"bpmn_xml": ["is", "set"],
		},
		fields=["name", "title", "bpmn_xml", "process_name"],
	)

	items = []
	for other in other_models:
		if not other.bpmn_xml:
			continue

		call_refs = _extract_call_activity_refs(other.bpmn_xml)
		for ref in call_refs:
			if ref["called_element"] in disabled_process_ids:
				disabled_sibling = disabled_process_ids[ref["called_element"]]
				items.append({
					"name": _(
						"'{0}' in {1} → references {2} (will be disabled)"
					).format(ref["name"], other.title, disabled_sibling.title),
					"exists": True,
					"type": "call_activity_ref",
					"detail": _(
						"Update calledElement from {0} to {1}?"
					).format(ref["called_element"], model.process_id),
					"source_model": other.name,
					"source_element_id": ref["bpmn_id"],
					"old_process_id": ref["called_element"],
					"new_process_id": model.process_id,
				})

	return items


@frappe.whitelist()
def validate_bpmn_readiness(xml_content: str, model_name: str = None) -> dict:
	"""
	Parse BPMN XML and check all prerequisites against the database.

	Shared validation used by both import (informational) and deploy (blocking).
	Checks 10 categories:
	  1. DocTypes         — referenced doctypes must exist
	  2. Fields           — referenced fields must exist on their doctypes
	  3. Workflow States  — referenced states must exist as Workflow State records
	  4. Workflow Actions — user task action labels must exist as Workflow Action Master records
	  5. Server Scripts   — script task references must exist
	  6. Lane Roles       — roles assigned to lanes must exist and be active
	  7. Frappe Workflows — active workflows are flagged as conflict warnings
	  8. Assignment Rules — active rules are flagged as conflict warnings
	  9. Prohibited Shapes — shapes that must not appear in executable processes
	 10. Call Activity Refs — call activities referencing models about to be disabled

	Args:
		xml_content: Raw BPMN XML text
		model_name:  Optional name of the model being deployed. When provided,
		             enables call activity reference checking (category 10).

	Returns:
		dict with categories, total_checked, total_missing, total_warnings, all_ready
	"""
	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	refs = _extract_bpmn_references(xml_content)
	referenced_doctypes = refs["doctypes"]
	referenced_fields = refs["fields"]
	referenced_states = refs["workflow_states"]
	referenced_actions = refs["workflow_actions"]
	referenced_scripts = refs["server_scripts"]
	referenced_lane_roles = refs["lane_roles"]
	apply_workflow_doctypes = refs["apply_workflow_doctypes"]
	_process_el = refs["process_el"]
	is_executable = False
	if _process_el is not None:
		is_executable = _process_el.get("isExecutable", "false").strip().lower() == "true"

	# ── Now run all checks ───────────────────────────────────────────────

	categories = []

	# 1. DocTypes
	doctype_items = []
	for dt in sorted(referenced_doctypes):
		exists = frappe.db.exists("DocType", dt)
		doctype_items.append({"name": dt, "exists": bool(exists), "type": "check"})
	if doctype_items:
		categories.append({
			"label": "DocTypes",
			"icon": "layout-template",
			"items": doctype_items,
		})

	# 2. Fields (only check if the parent DocType exists)
	field_items = []
	seen_fields = set()
	for dt, fieldname in referenced_fields:
		key = f"{fieldname} on {dt}"
		if key in seen_fields:
			continue
		seen_fields.add(key)

		if not frappe.db.exists("DocType", dt):
			# DocType doesn't exist — field check is moot, already flagged above
			field_items.append({"name": key, "exists": False, "type": "check"})
			continue

		try:
			meta = frappe.get_meta(dt)
			# has_field() only checks DocType-defined fields; system
			# metadata columns (owner, modified_by, creation, …) are
			# real DB columns on every table but absent from meta.fields.
			from frappe.model import default_fields, optional_fields

			exists = bool(
				meta.has_field(fieldname)
				or fieldname in default_fields
				or fieldname in optional_fields
			)
		except Exception:
			exists = False
		field_items.append({"name": key, "exists": exists, "type": "check"})

	if field_items:
		categories.append({
			"label": "Fields",
			"icon": "columns-3",
			"items": field_items,
		})

	# 3. Workflow States
	state_items = []
	for state in sorted(referenced_states):
		exists = frappe.db.exists("Workflow State", state)
		state_items.append({"name": state, "exists": bool(exists), "type": "check"})
	if state_items:
		categories.append({
			"label": "Workflow States",
			"icon": "git-branch",
			"items": state_items,
		})

	# 4. Workflow Action Master
	action_items = []
	for action_label in sorted(referenced_actions):
		exists = frappe.db.exists(
			"Workflow Action Master",
			{"workflow_action_name": action_label},
		)
		action_items.append({"name": action_label, "exists": bool(exists), "type": "check"})
	if action_items:
		categories.append({
			"label": "Workflow Actions",
			"icon": "zap",
			"items": action_items,
		})

	# 5. Server Scripts
	script_items = []
	for script_name in sorted(referenced_scripts):
		exists = frappe.db.exists("Server Script", script_name)
		script_items.append({"name": script_name, "exists": bool(exists), "type": "check"})
	if script_items:
		categories.append({
			"label": "Server Scripts",
			"icon": "file-code",
			"items": script_items,
		})

	# 6. Lane Roles
	role_items = []
	for role_name in sorted(referenced_lane_roles):
		role = frappe.db.get_value("Role", role_name, ["name", "disabled"], as_dict=True)
		if not role:
			role_items.append({"name": role_name, "exists": False, "type": "check"})
		elif role.disabled:
			role_items.append({
				"name": role_name,
				"exists": False,
				"type": "check",
				"detail": _("Role exists but is disabled"),
			})
		else:
			role_items.append({"name": role_name, "exists": True, "type": "check"})
	if role_items:
		categories.append({
			"label": "Lane Roles",
			"icon": "users",
			"items": role_items,
		})

	# 7. Frappe Workflows (conflict warning — active = should disable)
	from frappe.model.workflow import get_workflow_name

	workflow_items = []
	for dt in sorted(referenced_doctypes):
		if not frappe.db.exists("DocType", dt):
			continue
		wf_name = get_workflow_name(dt)
		if wf_name:
			workflow_items.append({
				"name": f"{wf_name} on {dt}",
				"exists": True,
				"type": "warning",
				"detail": _("Active Frappe Workflow — consider disabling to prevent conflicts with BPMN"),
			})
	if workflow_items:
		categories.append({
			"label": "Frappe Workflows",
			"icon": "workflow",
			"items": workflow_items,
		})

	# 8. Assignment Rules (conflict warning — active = should disable)
	assignment_items = []
	for dt in sorted(referenced_doctypes):
		if not frappe.db.exists("DocType", dt):
			continue
		active_rules = frappe.get_all(
			"Assignment Rule",
			filters={"document_type": dt, "disabled": 0},
			fields=["name"],
			limit=10,
		)
		for rule in active_rules:
			assignment_items.append({
				"name": f"{rule.name} on {dt}",
				"exists": True,
				"type": "warning",
				"detail": _("Active Assignment Rule — consider disabling to prevent conflicts with BPMN task assignment"),
			})
	if assignment_items:
		categories.append({
			"label": "Assignment Rules",
			"icon": "user-check",
			"items": assignment_items,
		})

	# 9. Prohibited Shapes (shapes that must not appear in an executable process)
	from one_bpmn.api.compilation import PROHIBITED_SHAPES

	prohibited_items = []
	if PROHIBITED_SHAPES:
		for child in _process_el or []:
			local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
			if local_tag in PROHIBITED_SHAPES:
				shape_info = PROHIBITED_SHAPES[local_tag]
				el_name = child.get("name", "").strip()
				el_id = child.get("id", "?")
				display_name = f'{shape_info["label"]}: "{el_name}"' if el_name else f'{shape_info["label"]} ({el_id})'
				prohibited_items.append({
					"name": display_name,
					"exists": False,
					"type": "check",
					"detail": shape_info.get("suggestion", ""),
				})
	if prohibited_items:
		categories.append({
			"label": "Prohibited Shapes",
			"icon": "ban",
			"items": prohibited_items,
		})

	# 10. Call Activity References (detect refs to models that will be disabled)
	if model_name:
		call_activity_ref_items = _check_call_activity_references(model_name)
		if call_activity_ref_items:
			categories.append({
				"label": "Call Activity References",
				"icon": "link-2",
				"items": call_activity_ref_items,
			})

	# 11. Eval Suites (deployment gating — non-blocking warnings)
	if model_name:
		eval_suite_items = []
		gating_suites = frappe.get_all(
			"AI Eval Suite",
			filters={"process_model": model_name, "gate_deployment": 1},
			fields=["name", "title"],
		)
		for suite in gating_suites:
			suite_title = suite.title or suite.name
			latest_runs = frappe.get_all(
				"AI Eval Run",
				filters={"suite": suite.name},
				fields=["name", "status", "started_at"],
				order_by="started_at desc",
				limit_page_length=1,
			)
			# Mirror compile_process_model's _check_eval_suite_gating logic:
			# only a Failed last run or no run at all is a warning.
			if not latest_runs:
				eval_suite_items.append({
					"name": suite_title,
					"exists": True,
					"type": "warning",
					"detail": _("Has never been run. Consider running it before deploying."),
				})
			elif latest_runs[0].status == "Failed":
				run_date = frappe.utils.formatdate(latest_runs[0].started_at)
				eval_suite_items.append({
					"name": suite_title,
					"exists": True,
					"type": "warning",
					"detail": _("Failed — last run on {0}. Consider re-running the suite before deploying.").format(run_date),
				})
			else:
				# Passed, Running, or Error — informational, non-blocking.
				eval_suite_items.append({
					"name": suite_title,
					"exists": True,
					"type": "check",
					"detail": _("Last eval run: {0}").format(latest_runs[0].status),
				})
		if eval_suite_items:
			categories.append({
				"label": "Eval Suites",
				"icon": "flask-conical",
				"items": eval_suite_items,
			})

	# ── Compute summary ──────────────────────────────────────────────────
	total_checked = 0
	total_missing = 0
	total_warnings = 0

	for cat in categories:
		for item in cat["items"]:
			total_checked += 1
			if item["type"] == "check" and not item["exists"]:
				total_missing += 1
			elif item["type"] in ("warning", "call_activity_ref"):
				total_warnings += 1

	return {
		"categories": categories,
		"total_checked": total_checked,
		"total_missing": total_missing,
		"total_warnings": total_warnings,
		"is_executable": is_executable,
		"all_ready": total_missing == 0 and is_executable,
	}


@frappe.whitelist(methods=["POST"])
def update_call_activity_references(references: str) -> dict:
	"""
	Batch-update Call Activity ``calledElement`` attributes in BPMN models.

	Called from the deploy readiness dialog when the user chooses
	"Update All" to rewrite Call Activity references from a model
	that is about to be disabled to the model being deployed.

	For each reference entry, the function:
	  1. Loads the source model's BPMN XML
	  2. Finds the ``<bpmn:callActivity>`` with the matching ``id``
	  3. Updates its ``calledElement`` attribute to ``new_process_id``
	  4. Saves the model (bypassing editability checks)

	Args:
		references: JSON-encoded list of dicts, each with:
		  - source_model:      BPMN Process Model name containing the Call Activity
		  - source_element_id: BPMN element ID of the Call Activity
		  - old_process_id:    Current calledElement value
		  - new_process_id:    New calledElement value to set

	Returns:
		dict with ``success`` (bool) and ``updated`` (int count)
	"""
	import xml.etree.ElementTree as _ET

	frappe.only_for(["System Manager", "Process Owner"])

	refs = json.loads(references) if isinstance(references, str) else references
	if not refs:
		return {"success": True, "updated": 0}

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	# Register common BPMN namespaces to prevent ns0/ns1 prefix pollution
	_ET.register_namespace("bpmn", BPMN_NS)
	_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
	_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
	_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
	_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

	updated = 0
	# Group by source_model to avoid re-parsing/re-saving the same model multiple times
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
			# Bypass editability check — this is a deployment-related operation
			doc.flags.skip_editability_check = True
			doc.save(ignore_permissions=True)

	return {"success": True, "updated": updated}


@frappe.whitelist()
def get_process_model(name: str) -> dict:
	"""
	Get a process model by name.

	Args:
		name: Name of the process model

	Returns:
		dict with model details
	"""
	if not name:
		frappe.throw(_("Model name is required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	# Sanitize XML for the viewer — encode any raw HTML attributes to base64
	# to prevent XML parse errors in the frontend BPMN viewer.
	xml_content = doc.bpmn_xml
	if xml_content:
		xml_content = _sanitize_html_attrs_for_viewer(xml_content)

	return {
		"name": doc.name,
		"model_name": doc.title,
		"title": doc.title,
		"process_id": doc.process_id,
		"description": doc.description,
		"xml_content": xml_content,
		"bpmn_xml": xml_content,
		"version": doc.version,
		"is_active": doc.is_active,
		"modified": doc.modified,
		"owner": doc.owner,
	}


@frappe.whitelist()
def list_process_models() -> list:
	"""
	List all process models accessible to the current user.

	Returns:
		list of process model summaries
	"""
	# Use get_all (no default page-size cap) so the Call Activity search dialog
	# and the process-id resolver never miss records beyond Frappe's default 20.
	models = frappe.get_all(
		"BPMN Process Model",
		fields=[
			"name",
			"title",
			"process_id",
			"description",
			"version",
			"is_active",
			"modified",
			"owner",
			"process_name",
		],
		order_by="modified desc",
	)

	# Add model_name alias for frontend compat
	for m in models:
		m["model_name"] = m["title"]

	return models


@frappe.whitelist()
def resolve_process_model_by_id(process_id: str) -> dict:
	"""
	Resolve a process_id to the BPMN Process Model that owns it.

	Used by the Call Activity editor to navigate to the linked diagram
	without requiring the frontend to fetch and filter the entire model list.

	Args:
		process_id: The BPMN process_id attribute (e.g. "Process_abc123")

	Returns:
		dict with name, title, process_name, process_id — or empty dict if not found
	"""
	if not process_id:
		return {}

	result = frappe.db.get_value(
		"BPMN Process Model",
		filters={"process_id": process_id},
		fieldname=["name", "title", "process_name", "process_id"],
		as_dict=True,
	)
	return result or {}


@frappe.whitelist()
def list_processes() -> list:
	"""
	List all Process records that have BPMN diagrams or are accessible for creating diagrams.

	Returns:
		list of Process records with diagram counts
	"""
	# Get all processes with their diagram counts
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

	# Get diagram counts per process
	diagram_counts = frappe.get_all(
		"BPMN Process Model", fields=["process_name", "count(*) as count"], group_by="process_name"
	)
	count_map = {d["process_name"]: d["count"] for d in diagram_counts}

	for proc in processes:
		proc["diagram_count"] = count_map.get(proc["name"], 0)

		# Get the active model (if any) for this process
		active_model = frappe.db.get_value(
			"BPMN Process Model",
			filters={"process_name": proc["name"], "is_active": 1},
			fieldname=["name", "modified"],
			as_dict=True,
		)

		if active_model:
			proc["status"] = "Active"
			proc["last_modified"] = active_model["modified"]
		elif proc["diagram_count"] > 0:
			# Models exist but none is active
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


@frappe.whitelist()
def get_process_diagrams(process: str) -> dict:
	"""
	Get all diagrams for a specific process.

	Args:
		process: Name of the Process

	Returns:
		dict with process details and list of diagrams
	"""
	if not process:
		frappe.throw(_("Process name is required"))

	# Get process details
	proc = frappe.get_doc("Process", process)
	proc.check_permission("read")

	# Get diagrams filtered by process
	diagrams = frappe.get_list(
		"BPMN Process Model",
		filters={"process_name": process},
		fields=["name", "title", "process_id", "description", "version", "is_active", "modified", "modified_by"],
		order_by="is_active desc, modified desc",
	)

	# Resolve user emails to full names for frontend display
	user_emails = list({d["modified_by"] for d in diagrams if d.get("modified_by")})
	user_names = {}
	if user_emails:
		for row in frappe.get_all("User", filters={"name": ["in", user_emails]}, fields=["name", "full_name"]):
			user_names[row["name"]] = row["full_name"]

	# Add model_name alias for frontend compat
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


@frappe.whitelist()
def update_diagram_order(process: str, order: list) -> dict:
	"""
	Update the display order of diagrams within a process.
	NOTE: display_order field was removed. This is now a no-op kept for frontend compat.

	Args:
		process: Name of the Process
		order: List of diagram names in desired order

	Returns:
		dict with success status
	"""
	return {"success": True}


@frappe.whitelist()
def delete_diagram(name: str) -> dict:
	"""
	Delete a BPMN process model diagram.

	Uses frappe.delete_doc() to ensure proper link checks, cascade
	cleanup (attachments, shares, todos, tags), and doc-level
	permission enforcement.

	Args:
		name: Name of the diagram to delete

	Returns:
		dict with success status
	"""

	if not name:
		frappe.throw(_("Process Map name is required"))

	from one_bpmn.api.canvas_comments import cleanup_process_model_assets
	cleanup_process_model_assets(name)
	# frappe.delete_doc handles: existence check, doc-level permissions,
	# link validation, child table cleanup, Version/Comment/File/DocShare/ToDo removal
	frappe.delete_doc("BPMN Process Model", name)

	return {"success": True}


@frappe.whitelist()
def rename_process_model(name: str, new_title: str) -> dict:
	"""
	Rename a BPMN Process Model — fast path.

	Skips doc.save() entirely since only the title/name is changing.
	This avoids the expensive validate hooks (cross-site editability
	check, XML parsing, version tracking with large XML diffing).

	Doc-level permission is enforced via frappe.get_doc().check_permission()
	to respect user-permission restrictions on specific records.

	Args:
		name: Current document name of the BPMN Process Model
		new_title: New human-readable title / name

	Returns:
		dict with new name and model_name
	"""
	if not name or not new_title:
		frappe.throw(_("Current name and new title are required"))

	new_title = new_title.strip()
	if not new_title:
		frappe.throw(_("New title cannot be empty"))

	# Doc-level permission check (respects user-permission restrictions)
	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("write")

	# Compare against the current title field (not the document name,
	# since allow_rename=1 means name and title can diverge)
	current_title = doc.title
	if new_title == current_title:
		return {"name": name, "model_name": current_title}

	# Global uniqueness check — title has unique=1 in the DocType schema.
	# Catch this before db.set_value to give a user-friendly error instead
	# of a raw IntegrityError.
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

	# Update title field directly — bypasses validate hooks
	# (no editability HTTP call, no XML parsing, no version bump, no track_changes diff)
	frappe.db.set_value("BPMN Process Model", name, "title", new_title, update_modified=True)

	# Rename the document (updates name + all Link references)
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
