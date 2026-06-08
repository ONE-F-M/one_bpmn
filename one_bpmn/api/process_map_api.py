# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

from lxml import etree as ET
import frappe
from frappe import _
from frappe.utils import cint


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

		if description is not None:
			doc.description = description
		doc.save()
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
		doc.insert()

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

	element_ids = set(re.findall(r'\bid="([^"]+)"', xml_content))

	rows_to_keep = []
	for row in doc.decision_tables:
		if row.decision_id in element_ids:
			rows_to_keep.append(row)
		else:
			# Remove from database directly since the row was inserted
			# via db_insert and may not be tracked by the ORM properly.
			if row.name:
				frappe.db.delete("Workflow Decision Table", {"name": row.name})

	doc.decision_tables = rows_to_keep

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
		doc.insert()
		action = "created"

	return {
		"name": doc.name,
		"model_name": doc.title,
		"process_id": doc.process_id,
		"action": action,
	}


@frappe.whitelist()
def validate_bpmn_readiness(xml_content: str) -> dict:
	"""
	Parse BPMN XML and check all prerequisites against the database.

	Shared validation used by both import (informational) and deploy (blocking).
	Checks 8 categories:
	  1. DocTypes         — referenced doctypes must exist
	  2. Fields           — referenced fields must exist on their doctypes
	  3. Workflow States  — referenced states must exist as Workflow State records
	  4. Workflow Actions — user task action labels must exist as Workflow Action Master records
	  5. Server Scripts   — script task references must exist
	  6. Lane Roles       — roles assigned to lanes must exist and be active
	  7. Frappe Workflows — active workflows are flagged as conflict warnings
	  8. Assignment Rules — active rules are flagged as conflict warnings

	Args:
		xml_content: Raw BPMN XML text

	Returns:
		dict with categories, total_checked, total_missing, total_warnings, all_ready
	"""
	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(xml_content.strip().encode("utf-8"))
	except Exception as exc:
		frappe.throw(_("Invalid BPMN XML: {0}").format(str(exc)))

	# ── Extract all references from the XML ──────────────────────────────

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
		# Extract spiffworkflow:* attributes
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

			# Multi-field rows (new format)
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

			# Legacy single-field format
			legacy_field = attrs.get("updateFieldName", "")
			if legacy_field and target_dt:
				referenced_fields.append((target_dt, legacy_field))

		else:
			# Other service types may reference a doctype
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

		# Assignee field → must exist on target doctype
		assignee_field = attrs.get("assigneeDocfield", "")
		if assignee_field and target_dt:
			referenced_fields.append((target_dt, assignee_field))

		# Task actions → Workflow Action Master
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
				# emailToDocFields may contain comma-separated field names
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

	# ── Extract process-level attributes ─────────────────────────────────
	_process_el = root.find(f"{{{BPMN_NS}}}process") or root.find("process")
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
			exists = bool(meta.has_field(fieldname))
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

	# ── Compute summary ──────────────────────────────────────────────────
	total_checked = 0
	total_missing = 0
	total_warnings = 0

	for cat in categories:
		for item in cat["items"]:
			total_checked += 1
			if item["type"] == "check" and not item["exists"]:
				total_missing += 1
			elif item["type"] == "warning":
				total_warnings += 1

	return {
		"categories": categories,
		"total_checked": total_checked,
		"total_missing": total_missing,
		"total_warnings": total_warnings,
		"is_executable": is_executable,
		"all_ready": total_missing == 0 and is_executable,
	}


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

	return {
		"name": doc.name,
		"model_name": doc.title,
		"title": doc.title,
		"process_id": doc.process_id,
		"description": doc.description,
		"xml_content": doc.bpmn_xml,
		"bpmn_xml": doc.bpmn_xml,
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
