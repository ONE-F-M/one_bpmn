# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

from lxml import etree as ET
import frappe
from frappe import _
from frappe.utils import cint

def _is_bpmn_super_user(user: str = None) -> bool:
	"""Return True if *user* holds the Super User Role defined in OneFM General Setting."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	try:
		super_user_role = frappe.db.get_single_value("OneFM General Setting", "super_user_role")
	except Exception:
		return False
	if not super_user_role:
		return False
	return super_user_role in frappe.get_roles(user)


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
	try:
		root = ET.fromstring(xml_content.strip().encode("utf-8"))
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


@frappe.whitelist()
def get_assignee_docfields(doctype: str) -> list:
	"""
	Safe endpoint for the BPMN editor to get all User-linked fields
	for a specific Target DocType. Includes standard fields like 'owner'.

	Args:
		doctype: Target DocType name

	Returns:
		list of dicts with fieldname and label
	"""
	if not doctype:
		return []

	# Use frappe.get_meta to get fields safely without querying DocField directly
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	# Start with standard User fields available on all DocTypes
	res = [
		{"fieldname": "owner", "label": _("Owner")},
		{"fieldname": "modified_by", "label": _("Modified By")},
	]

	# Add all Link fields pointing to User
	for f in meta.get("fields"):
		if f.fieldtype == "Link" and f.options == "User":
			res.append({"fieldname": f.fieldname, "label": f.label})

	return res


@frappe.whitelist()
def get_workflow_states_for_doctype(doctype: str) -> list:
	"""
	Return the workflow states (name + style) for the Workflow configured on
	the given DocType.  Used by the BPMN editor's Service Task "Apply Workflow"
	properties panel to populate the Workflow State autocomplete.

	Args:
		doctype: The Frappe DocType name (e.g. 'Employee Daily Action')

	Returns:
		list of dicts: [{"state": "Draft", "style": "Danger"}, ...]
		Empty list if no active workflow is configured for the DocType.
	"""
	if not doctype:
		return []

	# Find the active Workflow for this DocType
	workflows = frappe.get_all(
		"Workflow",
		filters={"document_type": doctype, "is_active": 1},
		fields=["name"],
		limit=1,
	)
	if not workflows:
		return []

	workflow_name = workflows[0]["name"]

	# Fetch the workflow states child table
	states = frappe.get_all(
		"Workflow Document State",
		filters={"parent": workflow_name},
		fields=["state", "doc_status", "style", "allow_edit"],
		order_by="idx asc",
	)

	return [
		{
			"state": s.get("state", ""),
			"style": s.get("style", ""),
			"doc_status": s.get("doc_status", ""),
			"allow_edit": s.get("allow_edit", ""),
		}
		for s in states
	]


# ============================================
# Shape Library API
# ============================================


@frappe.whitelist()
def get_shape_libraries() -> list:
	"""
	Get all shape libraries with their shapes.

	Returns:
		list of libraries with nested shapes
	"""
	libraries = frappe.get_list(
		"BPMN Shape Library",
		fields=["name", "library_name", "description", "icon", "display_order"],
		order_by="display_order asc",
	)

	# Get shapes for each library
	for lib in libraries:
		lib["shapes"] = frappe.get_list(
			"BPMN Custom Shape",
			filters={"library": lib["name"]},
			fields=["name", "shape_name", "shape_type", "svg_content", "display_order"],
			order_by="display_order asc",
		)

	return libraries


@frappe.whitelist()
def create_shape_library(library_name: str, description: str = None, icon: str = "folder") -> dict:
	"""
	Create a new shape library.

	Args:
		library_name: Name of the library
		description: Optional description
		icon: Lucide icon name

	Returns:
		dict with library details
	"""
	if not library_name:
		frappe.throw(_("Library name is required"))

	# Check if library already exists
	if frappe.db.exists("BPMN Shape Library", library_name):
		frappe.throw(_("Library '{0}' already exists").format(library_name))

	# Get next display order
	max_order = (
		frappe.db.get_value("BPMN Shape Library", fieldname="display_order", order_by="display_order desc")
		or 0
	)

	doc = frappe.new_doc("BPMN Shape Library")
	doc.library_name = library_name
	doc.description = description or ""
	doc.icon = icon
	doc.display_order = max_order + 1
	doc.insert()

	return {
		"name": doc.name,
		"library_name": doc.library_name,
		"description": doc.description,
		"icon": doc.icon,
	}


@frappe.whitelist()
def delete_shape_library(name: str) -> dict:
	"""
	Delete a shape library and all its shapes.

	Args:
		name: Name of the library to delete

	Returns:
		dict with success status
	"""
	if not name:
		frappe.throw(_("Library name is required"))

	# Delete all shapes in the library first
	shapes = frappe.get_all("BPMN Custom Shape", filters={"library": name})
	for shape in shapes:
		frappe.delete_doc("BPMN Custom Shape", shape.name)

	# Delete the library
	doc = frappe.get_doc("BPMN Shape Library", name)
	doc.check_permission("delete")
	doc.delete()

	return {"success": True}


@frappe.whitelist()
def upload_shape(library: str, shape_name: str, svg_content: str, shape_type: str = "decorative") -> dict:
	"""
	Upload a new custom shape.

	Args:
		library: Name of the parent library
		shape_name: Name of the shape
		svg_content: SVG markup
		shape_type: 'decorative' or 'bpmn_element'

	Returns:
		dict with shape details
	"""
	if not library or not shape_name or not svg_content:
		frappe.throw(_("Library, shape name, and SVG content are required"))

	# Validate library exists
	if not frappe.db.exists("BPMN Shape Library", library):
		frappe.throw(_("Library '{0}' does not exist").format(library))

	# Validate shape type
	if shape_type not in ["decorative", "bpmn_element"]:
		frappe.throw(_("Shape type must be 'decorative' or 'bpmn_element'"))

	# Get next display order within library
	max_order = (
		frappe.db.get_value(
			"BPMN Custom Shape",
			filters={"library": library},
			fieldname="display_order",
			order_by="display_order desc",
		)
		or 0
	)

	doc = frappe.new_doc("BPMN Custom Shape")
	doc.library = library
	doc.shape_name = shape_name
	doc.svg_content = svg_content
	doc.shape_type = shape_type
	doc.display_order = max_order + 1
	doc.insert()

	return {
		"name": doc.name,
		"shape_name": doc.shape_name,
		"library": doc.library,
		"shape_type": doc.shape_type,
	}


@frappe.whitelist()
def delete_shape(name: str) -> dict:
	"""
	Delete a custom shape.

	Args:
		name: Name of the shape to delete

	Returns:
		dict with success status
	"""
	if not name:
		frappe.throw(_("Shape name is required"))

	doc = frappe.get_doc("BPMN Custom Shape", name)
	doc.check_permission("delete")
	doc.delete()

	return {"success": True}


@frappe.whitelist()
def list_process_instances(
	filters=None, limit_start=0, limit_page_length=20, order_by="creation desc"
) -> list:
	"""
	List BPMN process instances with their active tasks joined as 'current_step'.
	"""

	if isinstance(filters, str):
		filters = json.loads(filters)

	if isinstance(limit_start, str):
		limit_start = int(limit_start)
	if isinstance(limit_page_length, str):
		limit_page_length = int(limit_page_length)

	instances = frappe.get_list(
		"BPMN Process Instance",
		fields=[
			"name",
			"process_model",
			"status",
			"context_doctype",
			"context_docname",
			"started_at",
			"initiated_by",
		],
		filters=filters,
		limit_start=limit_start,
		limit_page_length=limit_page_length,
		order_by=order_by,
	)

	if instances:
		instance_names = [d.name for d in instances]
		tasks = frappe.get_all(
			"BPMN Active Task",
			filters={
				"parent": ["in", instance_names],
				"parenttype": "BPMN Process Instance",
				"status": ["in", ["Waiting", ""]],
			},
			fields=["parent", "task_name", "status"],
		)

		from collections import defaultdict

		task_map = defaultdict(list)
		for t in tasks:
			task_map[t.parent].append(t.task_name)

		for d in instances:
			d.current_step = ", ".join(task_map.get(d.name, []))

	return instances


# ============================================
# Server Script API
# Uses ignore_permissions so Process Owners without the Script Manager role
# can still list/create Server Scripts via the BPMN editor.
# Creation is guarded to System Manager or Script Manager only.
# ============================================


def _derive_api_method(script_name: str) -> str:
	"""Convert a script name to a valid Frappe API method identifier."""
	import re
	method = script_name.lower()
	method = re.sub(r"[^a-z0-9\s_]", "", method)
	method = re.sub(r"\s+", "_", method)
	method = re.sub(r"_+", "_", method).strip("_")
	return method or "script"


@frappe.whitelist()
def create_server_script(
	script_name: str,
	script_type: str,
	script: str,
	reference_doctype: str = None,
	doctype_event: str = None,
	api_method: str = None,
	allow_guest: int = 0,
	event_frequency: str = None,
	cron_format: str = None,
	module: str = None,
) -> dict:
	if not script_name or not script_type or not script:
		frappe.throw(_("Script name, type, and content are required"))

	if not frappe.has_permission("Server Script", "create") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to create Server Scripts."),
			frappe.PermissionError,
		)

	doc = frappe.new_doc("Server Script")
	doc.__newname = script_name
	doc.script_type = script_type
	doc.script = script
	doc.disabled = 0  # enabled by default
	if reference_doctype:
		doc.reference_doctype = reference_doctype
	if doctype_event:
		doc.doctype_event = doctype_event
	# For API scripts, always set an api_method so Processa can reach it via REST
	if script_type == "API":
		resolved_method = api_method or _derive_api_method(script_name)
		doc.api_method = resolved_method
	elif api_method:
		doc.api_method = api_method
	if allow_guest:
		doc.allow_guest = int(allow_guest)
	if event_frequency:
		doc.event_frequency = event_frequency
	if cron_format:
		doc.cron_format = cron_format
	if module:
		doc.module = module

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		if frappe.db.exists("Server Script", script_name):
			# Script already exists — update in place instead of re-inserting
			doc = frappe.get_doc("Server Script", script_name)
			doc.script_type = script_type
			doc.script = script
			doc.disabled = 0
			if reference_doctype is not None:
				doc.reference_doctype = reference_doctype
			if doctype_event is not None:
				doc.doctype_event = doctype_event
			if script_type == "API":
				resolved_method = api_method or _derive_api_method(script_name)
				doc.api_method = resolved_method
			elif api_method is not None:
				doc.api_method = api_method
			if allow_guest is not None:
				doc.allow_guest = int(allow_guest)
			if event_frequency is not None:
				doc.event_frequency = event_frequency
			if cron_format is not None:
				doc.cron_format = cron_format
			if module is not None:
				doc.module = module
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)

	method = getattr(doc, "api_method", None) or ""
	return {
		"name":        doc.name,
		"script_type": doc.script_type,
		"api_method":  method,
		"api_url":     f"/api/method/{method}" if method else "",
	}


@frappe.whitelist()
def update_server_script(
	script_name: str,
	script: str,
	script_type: str = None,
	reference_doctype: str = None,
	doctype_event: str = None,
	api_method: str = None,
	allow_guest: int = None,
	event_frequency: str = None,
	cron_format: str = None,
	module: str = None,
) -> dict:
	"""Replace the script body (and optionally metadata) of an existing Server Script."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	if not frappe.has_permission("Server Script", "write") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to update Server Scripts."),
			frappe.PermissionError,
		)

	try:
		doc = frappe.get_doc("Server Script", script_name)
		doc.script = script
		if script_type:
			doc.script_type = script_type
		if reference_doctype is not None:
			doc.reference_doctype = reference_doctype
		if doctype_event is not None:
			doc.doctype_event = doctype_event
		if api_method is not None:
			doc.api_method = api_method
		if allow_guest is not None:
			doc.allow_guest = int(allow_guest)
		if event_frequency is not None:
			doc.event_frequency = event_frequency
		if cron_format is not None:
			doc.cron_format = cron_format
		if module is not None:
			doc.module = module
		original_user = frappe.session.user
		try:
			frappe.set_user("Administrator")
			doc.save(ignore_permissions=True)
		finally:
			frappe.set_user(original_user)
		method = doc.api_method or ""
		return {
			"name":        doc.name,
			"script_type": doc.script_type,
			"api_method":  method,
			"api_url":     f"/api/method/{method}" if method else "",
		}
	except frappe.DoesNotExistError:
		frappe.throw(_("Server Script '{0}' not found.").format(script_name))
	except Exception:
		frappe.log_error(title="Update Server Script Error", message=frappe.get_traceback())
		frappe.throw(_("Failed to update Server Script."))


@frappe.whitelist()
def check_server_script_exists(script_name: str) -> dict:
	"""Check if a Server Script document with the given name exists."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))
	return {"exists": bool(frappe.db.exists("Server Script", script_name))}


@frappe.whitelist()
def process_logix_message(
	message: str,
	session_id: str,
	conversation_name: str = None,
	chat_history: str = None,
	element_name: str = None,
	current_script: str = None,
) -> dict:
	"""Process a Logix AI chat message, persisting history in Chat Conversation."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		from one_bpmn.utils.chat_persistence import (
			create_conversation, save_user_message, save_bot_message, load_history,
		)

		# Create a new conversation on the first message
		if not conversation_name:
			label = element_name or "Script Task"
			conversation_name = create_conversation(
				agent_mode="Logix",
				title=f"Logix: {label}",
				user=frappe.session.user,
			)

		# Persist the user message
		save_user_message(conversation_name, message)

		# Load full history from DB (ignores the frontend-supplied chat_history)
		history = load_history(conversation_name)

		# Fetch the original script body for diff computation on MODIFY
		original_content = ""
		if current_script:
			try:
				original_content = frappe.get_doc("Server Script", current_script).script or ""
			except Exception:
				pass

		from one_bpmn.agents.google_adk.script_task_agent.script_task_agent import run_logix_message

		result = run_logix_message(
			message=message,
			chat_history=history,
			element_name=element_name or "",
			current_script=current_script or "",
			original_script_content=original_content,
		)

		# Persist the bot response
		save_bot_message(
			conversation_name,
			result.get("response", ""),
			metadata={"intent": result.get("intent")},
		)

		result["conversation_name"] = conversation_name
		return result

	except Exception:
		frappe.log_error(title="Logix Agent error", message=frappe.get_traceback())
		return {"intent": "ERROR", "response": "An unexpected error occurred. Please try again."}


@frappe.whitelist()
def prosally_chat(
	message: str,
	session_id: str,
	conversation_name: str = None,
	chat_history: str = None,
	process_name: str = "",
	diagram_name: str = "",
	confirmed_action: str = "",
	current_xml: str = "",
) -> dict:
	"""Process a ProsAlly chat message, persisting history in Chat Conversation."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		from one_bpmn.utils.chat_persistence import (
			create_conversation, save_user_message, save_bot_message, load_history,
		)

		# Create a new conversation on the first message
		if not conversation_name:
			label = process_name or diagram_name or "Process"
			conversation_name = create_conversation(
				agent_mode="ProsAlly",
				title=f"ProsAlly: {label}",
				user=frappe.session.user,
			)

		# Persist the user message
		save_user_message(conversation_name, message)

		# Load full history from DB
		history = load_history(conversation_name)

		from one_bpmn.agents.google_adk.prosally_agent.prosally_agent import run_prosally_message

		result = run_prosally_message(
			message=message,
			chat_history=history,
			process_name=process_name or "",
			diagram_name=diagram_name or "",
			confirmed_action=confirmed_action or "",
			current_xml=current_xml or "",
		)

		# Persist the bot response
		save_bot_message(
			conversation_name,
			result.get("response", ""),
			metadata={"intent": result.get("intent"), "action_intent": result.get("action_intent")},
		)

		result["conversation_name"] = conversation_name
		return result

	except Exception:
		frappe.log_error(title="ProsAlly Agent error", message=frappe.get_traceback())
		return {"intent": "ERROR", "response": "An unexpected error occurred. Please try again."}


@frappe.whitelist()
def toggle_server_script(script_name: str, disabled: int) -> dict:
	"""Toggle the disabled status of a Server Script record."""
	if not script_name:
		frappe.throw(_("Script name is required"))

	# Permission check: Script Manager or System Manager
	if not frappe.has_permission("Server Script", "write") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to toggle Server Scripts."),
			frappe.PermissionError,
		)

	# Use set_value to bypass ServerScript validation logic which checks for
	# exactly the 'Script Manager' role. The has_permission check above
	# already proves the current user is authorized (e.g. System Manager).
	frappe.db.set_value(
		"Server Script",
		script_name,
		"disabled",
		int(disabled),
		update_modified=True
	)

	return {"name": script_name, "disabled": int(disabled)}



# ============================================
# Notification API
# Creates Notification documents from the BPMN Send Task dialog.
# New notifications are disabled by default (enabled when deployed).
# ============================================


@frappe.whitelist()
def create_notification(
	notification_name: str,
	channel: str,
	document_type: str,
	event: str = "New",
	subject: str = None,
	message: str = None,
	message_type: str = "Markdown",
	condition: str = None,
	module: str = None,
	# Email-specific
	sender: str = None,
	sender_email: str = None,
	attach_print: int = 0,
	print_format: str = None,
	send_system_notification: int = 0,
	# Slack-specific
	slack_webhook_url: str = None,
	# WhatsApp-specific  (Twilio integration)
	twilio_number: str = None,
	# Trigger fields
	method: str = None,
	date_changed: str = None,
	days_in_advance: int = 0,
	value_changed: str = None,
	# Recipients
	send_to_all_assignees: int = 0,
	recipients: str = None,  # JSON string of recipient rows
	# After Alert
	set_property_after_alert: str = None,
	property_value: str = None,
) -> dict:
	"""
	Create a Notification document from the BPMN Send Task dialog.

	The notification is created with enabled=0 (disabled by default).
	It should be enabled when the process is deployed.

	Args:
		notification_name: Human-readable name for the notification
		channel: Email / Slack / System Notification / SMS / WhatsApp
		document_type: The DocType this notification is linked to
		event: Trigger event (New/Save/Submit/Cancel/Days After/Days Before/Value Change/Method/Custom)
		subject: Notification subject line (Jinja template)
		message: Message body (Jinja template)
		message_type: Markdown / HTML / Plain Text
		condition: Python condition expression
		module: Module for export
		sender: Email Account link (Email channel)
		sender_email: Sender email address (Email channel)
		attach_print: Whether to attach print (Email channel)
		print_format: Print Format link (Email channel)
		send_system_notification: Also send system notification flag
		slack_webhook_url: Slack Webhook URL link (Slack channel)
		twilio_number: Communication Medium link (WhatsApp channel)
		method: Trigger method name (Method event)
		date_changed: Date field name (Days After/Before events)
		days_in_advance: Number of days (Days After/Before events)
		value_changed: Field name (Value Change event)
		send_to_all_assignees: Send to all document assignees
		recipients: JSON array of recipient row objects
		set_property_after_alert: Field to set after alert fires
		property_value: Value to set

	Returns:
		dict with name and channel
	"""
	import json as _json

	if not notification_name or not channel or not document_type:
		frappe.throw(_("Notification name, channel, and document type are required"))

	if not frappe.has_permission("Notification", "create") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the System Manager role to create Notifications."),
			frappe.PermissionError,
		)

	doc = frappe.new_doc("Notification")
	doc.__newname = notification_name
	doc.subject = subject or notification_name
	doc.channel = channel
	doc.document_type = document_type
	doc.event = event or "New"
	doc.enabled = 0  # Disabled by default — enabled when deployed
	doc.message_type = message_type or "Markdown"

	if message:
		doc.message = message
	if condition:
		doc.condition = condition
	if module:
		doc.module = module

	# Email-specific fields
	if sender:
		doc.sender = sender
	if sender_email:
		doc.sender_email = sender_email
	if int(attach_print or 0):
		doc.attach_print = 1
	if print_format:
		doc.print_format = print_format
	if int(send_system_notification or 0):
		doc.send_system_notification = 1

	# Slack-specific
	if slack_webhook_url:
		doc.slack_webhook_url = slack_webhook_url

	# WhatsApp-specific (Twilio)
	if twilio_number:
		doc.twilio_number = twilio_number

	# Trigger fields
	if method:
		doc.method = method
	if date_changed:
		doc.date_changed = date_changed
	if days_in_advance:
		doc.days_in_advance = int(days_in_advance)
	if value_changed:
		doc.value_changed = value_changed

	# After Alert
	if set_property_after_alert:
		doc.set_property_after_alert = set_property_after_alert
	if property_value:
		doc.property_value = property_value

	# Recipients
	if int(send_to_all_assignees or 0):
		doc.send_to_all_assignees = 1

	if recipients:
		if isinstance(recipients, str):
			try:
				rows = _json.loads(recipients)
			except (ValueError, _json.JSONDecodeError):
				frappe.throw("Recipients must be a valid JSON array of objects.", frappe.ValidationError)
		else:
			rows = recipients

		if not isinstance(rows, list):
			frappe.throw("Recipients must be a list of objects.", frappe.ValidationError)

		for row in rows:
			if not isinstance(row, dict):
				frappe.throw("Each recipient entry must be an object.", frappe.ValidationError)
			doc.append(
				"recipients",
				{
					"receiver_by_document_field": row.get("receiver_by_document_field", ""),
					"receiver_by_role": row.get("receiver_by_role", ""),
					"cc": row.get("cc", ""),
					"bcc": row.get("bcc", ""),
					"condition": row.get("condition", ""),
				},
			)

	# Elevate to bypass permission checks in the Notification controller.
	# The role guard above already ensures only authorised users reach here.
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)

	return {"name": doc.name, "channel": doc.channel}


# ============================================
# Pathfinder Log — Process Editability Check
# ============================================
# The Processa BPMN editor is deployed on two sites:
#   Production (one-fm.com)        — always read-only
#   BA site (business-analyst...)  — editable only when an active Pathfinder Log exists
#
# The Pathfinder Log doctype lives in the one_fm app on Production.
# These proxy endpoints let the BA site frontend check editability
# without making cross-origin requests directly.


def _is_production_site() -> bool:
	"""Return True if the current Frappe site IS the Production instance."""
	settings = frappe.get_single("Processa Settings")
	if not settings.enabled:
		return False

	production_url = (settings.production_url or "").rstrip("/")
	if not production_url:
		# If production_url is not configured, assume we are NOT production
		# (safe default: allow the editability check to proceed).
		return False
	site_url = frappe.utils.get_url().rstrip("/")
	return site_url == production_url


def _is_local_dev_mode() -> bool:
	"""Return True when production API credentials are NOT configured.

	In local dev the one_fm app (with Pathfinder Log) lives on the same
	bench, so we can call its API directly without HTTP.
	"""
	settings = frappe.get_single("Processa Settings")
	if settings.enabled:
		production_url = settings.production_url
		api_key = settings.get_password("production_api_key")
		api_secret = settings.get_password("production_api_secret")
		if production_url and api_key and api_secret:
			return False

	# Fallback to site_config.json (frappe.conf)
	production_url = frappe.conf.get("production_url")
	api_key = frappe.conf.get("production_api_key")
	api_secret = frappe.conf.get("production_api_secret")
	return not (production_url and api_key and api_secret)


@frappe.whitelist()
def check_and_update_editor_lock(model_name: str) -> list[dict[str, str | None]]:
	"""
	Track active editors for a BPMN Process Model using Frappe cache.

	Returns a list of dictionaries for other active users, where each
	dictionary contains ``name``, ``full_name``, and ``user_image``.
	"""
	if not model_name:
		return []

	current_user = frappe.session.user
	if current_user == "Guest":
		return []

	doc = frappe.get_doc("BPMN Process Model", model_name)
	doc.check_permission("read")
	cache_key = f"bpmn_editor_lock:{model_name}"
	active_editors = frappe.cache.get_value(cache_key) or {}

	import time

	now = time.time()

	# Clean up expired heartbeats (> 45s) and identify others
	other_editors = []
	updated_editors = {}

	for user, timestamp in active_editors.items():
		if now - timestamp < 45:
			if user != current_user:
				other_editors.append(user)
				updated_editors[user] = timestamp

	# Add current user
	updated_editors[current_user] = now

	# Save back to cache (60s TTL)
	frappe.cache.set_value(cache_key, updated_editors, expires_in_sec=60)

	# Return detailed user info for other editors for better UX (avatars)
	if other_editors:
		return frappe.get_all(
			"User", filters={"name": ["in", other_editors]}, fields=["name", "full_name", "user_image"]
		)

	return []


def _call_local_pathfinder_api(method_path: str, params: dict) -> dict:
	"""Call a pathfinder API method directly (same bench, no HTTP).

	Used as a fallback in local dev when production credentials are not
	configured.
	"""
	import importlib

	# method_path looks like "one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.is_process_editable"
	module_path, func_name = method_path.rsplit(".", 1)
	module = importlib.import_module(module_path)
	func = getattr(module, func_name)
	return func(**params)


def _call_production_api(method: str, params: dict) -> dict:
	"""
	Call a whitelisted method on the Production site using API key auth.

	Reads `production_url`, `production_api_key`, and
	`production_api_secret` from Processa Settings DocType.

	Falls back to a direct local call when credentials are not configured
	(local development mode).
	"""
	import requests

	# Local dev fallback — call directly on the same bench
	if _is_local_dev_mode():
		return _call_local_pathfinder_api(method, params)

	settings = frappe.get_single("Processa Settings")
	production_url = None
	api_key = None
	api_secret = None

	if settings.enabled:
		production_url = (settings.production_url or "").rstrip("/")
		api_key = settings.get_password("production_api_key")
		api_secret = settings.get_password("production_api_secret")

	# Fallback to site_config.json if settings are disabled or incomplete
	if not (production_url and api_key and api_secret):
		production_url = (frappe.conf.get("production_url") or "").rstrip("/")
		api_key = frappe.conf.get("production_api_key")
		api_secret = frappe.conf.get("production_api_secret")

	if not production_url or not api_key or not api_secret:
		frappe.throw(
			_(
				"Production API credentials are not configured. "
				"Please go to Processa Settings to configure the "
				"Production URL, API Key, and API Secret."
			)
		)

	url = f"{production_url}/api/method/{method}"
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}

	try:
		resp = requests.get(url, params=params, headers=headers, timeout=10)
		resp.raise_for_status()
		data = resp.json()
		return data.get("message", data)
	except requests.exceptions.Timeout:
		frappe.throw(_("Production API request timed out. Please try again."))
	except requests.exceptions.ConnectionError:
		frappe.throw(_("Cannot reach Production site. Please check connectivity."))
	except Exception as e:
		frappe.log_error(
			title="Production API call failed",
			message=f"Method: {method}\nParams: {json.dumps(params)}\nError: {str(e)}",
		)
		frappe.throw(_("Failed to check process editability. Please try again or contact support."))


@frappe.whitelist()
def check_process_editable(process_name: str) -> dict:
	"""
	Check if a single process is editable (has an active Pathfinder Log).

	On Production: always returns editable=False.
	On BA site: proxies the call to Production's API.
	Local dev override: set bypass_process_lock=true in site_config.json
	  to skip the Pathfinder Log gate entirely and always return editable=True.

	Args:
		process_name: Name of the Process record.

	Returns:
		dict with editable, pathfinder_log, workflow_state, reason
	"""
	if not process_name:
		frappe.throw(_("Process name is required"))

	# ── Local dev bypass ────────────────────────────────────────────────────
	# Set `"bypass_process_lock": true` in site_config.json to unlock all
	# processes for editing without needing a Pathfinder Log.
	if frappe.conf.get("bypass_process_lock"):
		return {
			"editable": True,
			"pathfinder_log": None,
			"workflow_state": None,
			"reason": "Local dev mode: bypass_process_lock is enabled in site_config.json.",
		}

	if _is_production_site():
		return {
			"editable": False,
			"pathfinder_log": None,
			"workflow_state": None,
			"reason": "Production site is always read-only.",
		}

	result = _call_production_api(
		"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.is_process_editable",
		{"process_name": process_name},
	)

	# Add a human-readable reason for the frontend
	if result.get("editable"):
		result["reason"] = f"Active Pathfinder Log: {result.get('pathfinder_log')}"
	else:
		result["reason"] = "No active Pathfinder Log. Create or activate one to enable editing."

	return result


@frappe.whitelist()
def bulk_check_processes_editable(process_names: str) -> dict:
	"""
	Batch check editability for multiple processes.

	On Production: returns all as non-editable.
	On BA site: proxies to Production's bulk API.

	Args:
		process_names: JSON-encoded list of process name strings.

	Returns:
		dict mapping process name → editability info
	"""
	import json

	# Safe JSON parsing with validation
	try:
		if isinstance(process_names, str):
			process_names_list = frappe.parse_json(process_names)
		else:
			process_names_list = process_names
	except Exception:
		frappe.throw(
			_("Invalid process_names: expected a JSON-encoded list of strings."),
			title=_("Validation Error"),
		)

	if not isinstance(process_names_list, list):
		frappe.throw(_("process_names must be a list"))

	# ── Local dev bypass ────────────────────────────────────────────────────
	if frappe.conf.get("bypass_process_lock"):
		return {
			pname: {
				"editable": True,
				"pathfinder_log": None,
				"workflow_state": None,
				"reason": "Local dev mode: bypass_process_lock is enabled.",
			}
			for pname in process_names_list
		}

	if _is_production_site():
		return {
			pname: {
				"editable": False,
				"pathfinder_log": None,
				"workflow_state": None,
			}
			for pname in process_names_list
		}

	return _call_production_api(
		"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.bulk_check_process_editable",
		{"process_names": json.dumps(process_names_list)},
	)


# ============================================
# Diagram Version History (for visual diffing)
# ============================================


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


# ============================================
# SpiffWorkflow Engine API
# ============================================


def _sanitize_bpmn_xml(bpmn_xml: str) -> str:
	"""
	Remove orphaned references to deleted elements from a BPMN XML string.

	When an element is deleted in bpmn-js the definition is removed but
	references in lanes (flowNodeRef), sequence flows, associations, and
	diagram shapes are sometimes left as orphans.  SpiffWorkflow then raises
	"found two items, perhaps a form has the same ID?".

	This function collects all IDs actually defined in the process body, then
	strips every reference that points to a non-existent ID.
	Returns sanitized XML as a string. Falls back to original XML on any error.
	"""
	try:
		from lxml import etree

		BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
		BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"

		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"))

		# 1. Collect IDs of elements actually defined inside <bpmn:process>
		defined_ids = set()
		for process in root.iter(f"{{{BPMN}}}process"):
			for child in process:
				eid = child.get("id")
				if eid:
					defined_ids.add(eid)

		# 2. Strip orphaned <bpmn:flowNodeRef> entries inside lanes
		for lane in root.iter(f"{{{BPMN}}}lane"):
			to_remove = [
				fnr
				for fnr in lane.findall(f"{{{BPMN}}}flowNodeRef")
				if (fnr.text or "").strip() not in defined_ids
			]
			for fnr in to_remove:
				lane.remove(fnr)

		# 3. Strip sequence flows whose source or target no longer exists
		for process in root.iter(f"{{{BPMN}}}process"):
			to_remove = [
				sf
				for sf in process.findall(f"{{{BPMN}}}sequenceFlow")
				if sf.get("sourceRef", "") not in defined_ids or sf.get("targetRef", "") not in defined_ids
			]
			for sf in to_remove:
				process.remove(sf)

		# 4. Strip associations whose source AND target are both gone
		for collab in root.iter(f"{{{BPMN}}}collaboration"):
			to_remove = [
				a
				for a in collab.findall(f"{{{BPMN}}}association")
				if a.get("sourceRef", "") not in defined_ids and a.get("targetRef", "") not in defined_ids
			]
			for a in to_remove:
				collab.remove(a)

		# 5. Strip BPMNShape entries whose bpmnElement no longer exists
		#    Only remove shapes for process-flow elements — not lane/participant
		#    shapes which are legitimately defined outside <bpmn:process>.
		for plane in root.iter(f"{{{BPMNDI}}}BPMNPlane"):
			lane_participant_ids = {
				el.get("id")
				for el in root.iter()
				if el.get("id")
				and el.tag.split("}")[-1] in ("lane", "participant", "laneSet", "collaboration")
			}
			to_remove = [
				shape
				for shape in plane.findall(f"{{{BPMNDI}}}BPMNShape")
				if shape.get("bpmnElement", "") not in defined_ids
				and shape.get("bpmnElement", "") not in lane_participant_ids
			]
			for shape in to_remove:
				plane.remove(shape)

		return etree.tostring(root, encoding="unicode", xml_declaration=False)

	except Exception:
		# If sanitisation fails for any reason, return the original and let
		# SpiffWorkflow's own parser produce the actual error message.
		return bpmn_xml


def _extract_service_task_config(bpmn_xml: str) -> dict:
	"""
	Parse the BPMN XML and extract every ``spiffworkflow:*`` attribute set on
	``<bpmn:serviceTask>`` elements.

	The bpmn-js moddle stores custom properties as XML attributes using the
	spiffworkflow namespace (e.g. ``spiffworkflow:serviceType``).
	SpiffWorkflow's Python parser does NOT read these attributes, so they
	would otherwise be invisible at runtime.  We extract them once at compile
	time and embed them in the serialized spec so the engine can dispatch to
	the correct handler when the task executes.

	Returns:
		dict keyed by BPMN element ID::

			{
				"Activity_097ls3l": {
					"serviceType": "apply_workflow",
					"workflowState": "Draft",
					"onlyAllowEdit": "Employee",
				},
			}
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for service_task in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		bpmn_id = service_task.get("id")
		if not bpmn_id:
			continue

		task_cfg = {}
		for attr_name, attr_value in service_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}") :]
				task_cfg[key] = attr_value

		if task_cfg:
			config[bpmn_id] = task_cfg

	return config


def _extract_user_task_config(bpmn_xml: str) -> dict:
	"""
	Parse the BPMN XML and extract every ``spiffworkflow:*`` attribute set on
	``<bpmn:userTask>`` elements (assignment mode, doctype, users list, etc.).

	Mirors ``_extract_service_task_config`` but for UserTasks.

	Returns:
		dict keyed by BPMN element ID::

			{
				"Activity_1abc": {
					"assigneeMode": "Round Robin",
					"assigneeUsers": "admin@example.com,hr@example.com",
					"targetDoctype": "Employee",
				},
			}
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for user_task in root.iter(f"{{{BPMN_NS}}}userTask"):
		bpmn_id = user_task.get("id")
		if not bpmn_id:
			continue

		task_cfg = {}
		for attr_name, attr_value in user_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}") :]
				task_cfg[key] = attr_value

		if task_cfg:
			config[bpmn_id] = task_cfg

	return config


def _validate_timer_granularity(bpmn_xml: str) -> None:
	"""
	Validate that no timer event uses second-level precision.

	Frappe's scheduler runs at minute intervals only — values like
	``PT15S`` (15 seconds) or ``R5/PT10S`` (every 10 seconds, 5 times)
	will never fire correctly. This validation rejects such values at
	deploy time with a clear error message.

	Checks all ``<bpmn:timerEventDefinition>`` elements in the XML:
	  - ``<bpmn:timeDuration>`` values ending with digits + 'S' (e.g. PT15S)
	  - ``<bpmn:timeCycle>`` values with second-level ISO intervals (e.g. R5/PT10S)
	"""
	import re
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return  # XML errors are caught elsewhere

	errors = []

	for timer_def in root.iter(f"{{{BPMN_NS}}}timerEventDefinition"):
		# Find the parent element name for a better error message
		parent = None
		for elem in root.iter():
			if timer_def in list(elem):
				parent = elem
				break
		parent_id = parent.get("id", "unknown") if parent is not None else "unknown"
		parent_name = parent.get("name", "") if parent is not None else ""
		label = parent_name or parent_id

		# Check timeDuration
		duration_el = timer_def.find(f"{{{BPMN_NS}}}timeDuration")
		if duration_el is not None and duration_el.text:
			val = duration_el.text.strip()
			# Match durations with only seconds: PT15S, PT30S, etc.
			# Also match mixed with seconds: PT1M30S
			if re.search(r"\d+S\s*$", val, re.IGNORECASE):
				if not re.search(r"[DHMY]\d*M", val, re.IGNORECASE) and not re.search(
					r"\d+M\d+S", val, re.IGNORECASE
				):
					# Pure seconds like PT15S
					errors.append(
						f'Timer "{label}": Duration "{val}" uses seconds. '
						f"Minimum supported duration is 1 minute (PT1M)."
					)
				else:
					# Mixed with seconds like PT1M30S — warn
					errors.append(
						f'Timer "{label}": Duration "{val}" includes a seconds component. '
						f"Frappe scheduler runs at minute intervals — seconds will be ignored. "
						f"Use whole minutes instead."
					)

		# Check timeCycle
		cycle_el = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
		if cycle_el is not None and cycle_el.text:
			val = cycle_el.text.strip()
			# ISO 8601 repeating with seconds: R5/PT10S, R/PT30S
			if re.search(r"/PT\d+S\s*$", val, re.IGNORECASE):
				errors.append(
					f'Timer "{label}": Cycle "{val}" uses second-level intervals. '
					f"Minimum cycle interval is 1 minute. Use cron expressions or PT1M."
				)

	if errors:
		frappe.throw(
			_(
				"Timer validation failed — Frappe scheduler only supports minute-level precision:<br><br>"
				+ "<br>".join(f"• {e}" for e in errors)
			),
			title=_("Invalid Timer Configuration"),
		)


def _populate_start_events(model, bpmn_xml: str) -> None:
	"""
	Parse the BPMN XML and populate the ``start_events`` child table on the
	Process Model with one row per ``<bpmn:startEvent>`` element.

	Detects event type from child definitions:
	  - ``<bpmn:conditionalEventDefinition>`` → Conditional
	  - ``<bpmn:timerEventDefinition>``       → Timer
	  - ``<bpmn:signalEventDefinition>``      → Signal
	  - No definition element                 → None (plain start)

	Extracts configuration from ``spiffworkflow:*`` attributes:
	  - triggerWorkflowState → workflow_state_condition
	  - triggerDoctype       → trigger_doctype
	  - triggerType          → trigger_event (e.g. "After Insert")
	  - cronExpression       → cron_expression (on timer definitions)

	Also syncs model-level trigger fields (trigger_type, trigger_doctype,
	trigger_event) so that trigger.py can fire process instances.

	Note: This function modifies the model in-memory only — the caller is
	responsible for calling model.save().
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	# Clear existing rows
	model.start_events = []

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		frappe.log_error(
			title="BPMN: Failed to parse XML for start events",
			message=frappe.get_traceback(),
		)
		return

	for start_event in root.iter(f"{{{BPMN_NS}}}startEvent"):
		bpmn_id = start_event.get("id", "")

		# ── Detect event type from child definition elements ───────────
		event_type = "None"
		cron_expr = ""

		cond_def = start_event.find(f"{{{BPMN_NS}}}conditionalEventDefinition")
		timer_def = start_event.find(f"{{{BPMN_NS}}}timerEventDefinition")
		signal_def = start_event.find(f"{{{BPMN_NS}}}signalEventDefinition")

		if cond_def is not None:
			event_type = "Conditional"
		elif timer_def is not None:
			event_type = "Timer"
			# Extract cron from timer definition's spiffworkflow:cronExpression
			cron_expr = timer_def.get(f"{{{SPIFF_NS}}}cronExpression", "")
			# Also check for timeCycle/timeDuration child elements
			if not cron_expr:
				cycle = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
				if cycle is not None and cycle.text:
					cron_expr = cycle.text.strip()
		elif signal_def is not None:
			event_type = "Signal"

		# ── Extract spiffworkflow:* attributes from the start event ────
		workflow_state = start_event.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		trigger_doctype = start_event.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		trigger_type_attr = start_event.get(f"{{{SPIFF_NS}}}triggerType", "")

		# Also check conditional definition for nested attributes
		if cond_def is not None and not workflow_state:
			workflow_state = cond_def.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		if cond_def is not None and not trigger_doctype:
			trigger_doctype = cond_def.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		if cond_def is not None and not trigger_type_attr:
			trigger_type_attr = cond_def.get(f"{{{SPIFF_NS}}}triggerType", "")

		# ── Resolve trigger_event from XML or fall back to model field ──
		trigger_event = trigger_type_attr or model.trigger_event or ""

		# ── Determine trigger_type for this specific start event ──
		trigger_type = "API"  # Default
		if trigger_doctype:
			trigger_type = "DocType Event"
		elif cron_expr:
			trigger_type = "Scheduler Event"

		model.append(
			"start_events",
			{
				"event_type": event_type,
				"bpmn_element_id": bpmn_id,
				"trigger_type": trigger_type,
				"trigger_doctype": trigger_doctype,
				"trigger_event": trigger_event,
				"workflow_state_condition": workflow_state,
				"cron_expression": cron_expr,
			},
		)

	# ── Sync spec → model-level trigger fields (DECOMMISSIONED) ────────────────
	# Note: Model-level trigger fields are now kept for backward compatibility
	# but are no longer updated. trigger.py and tasks.py now look at the
	# start_events child table directly to support multiple start triggers.
	pass


def _get_linked_server_scripts(spec_json: str) -> set:
	"""
	Extract the set of Server Script names referenced by Script Tasks
	in a BPMN Process Model's serialized spec.

	Args:
		spec_json: JSON string from BPMN Process Model.serialized_spec

	Returns:
		set of Server Script names (may be empty)
	"""
	if not spec_json:
		return set()
	try:
		spec_data = json.loads(spec_json)
	except (json.JSONDecodeError, TypeError):
		return set()

	scripts = set()
	for cfg in spec_data.get("script_task_extensions", {}).values():
		name = cfg.get("serverScript", "")
		if name:
			scripts.add(name)
	return scripts


def _activate_deployed_model(model, script_extensions: dict) -> None:
	"""
	Handle the deployment lifecycle for a BPMN Process Model:

	1. Mark the model as active (``is_active = 1``)
	2. Deactivate sibling models with the same ``process_name``
	3. Enable Server Scripts linked to the deployed model
	4. Disable Server Scripts linked to deactivated siblings
	   (unless shared with the active model)

	Modifies the model in-memory — the caller is responsible for
	calling ``model.save()``.

	Args:
		model:             BPMN Process Model document (in-memory)
		script_extensions: dict from ``_extract_script_task_config()``
	"""

	model.is_active = 1
	model.deployed_at = frappe.utils.now()
	model.deployed_by = frappe.session.user

	# Server scripts referenced by the deployed model
	active_scripts = set()
	for cfg in (script_extensions or {}).values():
		if cfg.get("serverScript"):
			active_scripts.add(cfg["serverScript"])

	# Fetch active siblings once — used for both version calculation and deactivation
	siblings = []
	if model.process_name:
		siblings = frappe.get_all(
			"BPMN Process Model",
			filters={
				"process_name": model.process_name,
				"is_active": 1,
				"name": ["!=", model.name],
			},
			fields=["name", "version", "serialized_spec"],
		)

	# Version: max sibling version + 1, or 1 if no siblings
	max_sibling_version = max((s.version or 0 for s in siblings), default=0)
	model.version = max_sibling_version + 1

	# Deactivate sibling models and their exclusive server scripts
	if siblings:
		sibling_scripts = set()
		for s in siblings:
			sibling_scripts |= _get_linked_server_scripts(s.serialized_spec)
			frappe.db.set_value("BPMN Process Model", s.name, "is_active", 0)

		# Disable scripts exclusive to deactivated siblings
		for script_name in (sibling_scripts - active_scripts):
			if frappe.db.exists("Server Script", script_name):
				frappe.db.set_value("Server Script", script_name, "disabled", 1)

	# Enable server scripts linked to the deployed model
	for script_name in active_scripts:
		if frappe.db.exists("Server Script", script_name):
			frappe.db.set_value("Server Script", script_name, "disabled", 0)


def _update_round_robin_in_model(model_name: str, task_bpmn_id: str, last_user: str) -> None:
	"""
	Update the round-robin tracking state on the BPMN Process Model:

	  1. Reads/increments ``next_idx`` in ``round_robin_state`` JSON field.
	  2. Updates ``spiffworkflow:roundRobinLastUser`` attribute in the stored
		 BPMN XML so the editor reflects the last-assigned user.
	  3. Saves the model with ``ignore_permissions=True`` (called from engine).
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		model = frappe.get_doc("BPMN Process Model", model_name)
		state = json.loads(model.round_robin_state or "{}")
		if task_bpmn_id not in state:
			state[task_bpmn_id] = {"next_idx": 0, "last_user": ""}
		state[task_bpmn_id]["last_user"] = last_user
		model.round_robin_state = json.dumps(state)

		# ---  Also patch the BPMN XML so the editor shows the last user  ---
		if model.bpmn_xml:
			try:
				_ET.register_namespace("", BPMN_NS)
				_ET.register_namespace("spiffworkflow", SPIFF_NS)
				root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
				attr_key = f"{{{SPIFF_NS}}}roundRobinLastUser"
				for el in root.iter(f"{{{BPMN_NS}}}userTask"):
					if el.get("id") == task_bpmn_id:
						el.set(attr_key, last_user)
						break
				model.bpmn_xml = _ET.tostring(root, encoding="unicode", xml_declaration=False)
			except Exception:
				pass  # XML patch failure is non-fatal — state field is the truth

		model.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="BPMN: round-robin state update failed",
			message=frappe.get_traceback(),
		)


def _ensure_script_task_inline_scripts(bpmn_xml: str) -> str:
	"""
	Ensure every ``<bpmn:scriptTask>`` element in the BPMN XML has at least
	a ``<bpmn:script>pass</bpmn:script>`` child element.

	SpiffWorkflow's parser asserts exactly one ``<bpmn:script>`` element per
	Script Task.  When a designer uses ONLY the Server Script picker (our
	custom behaviour) and does not write any inline script, bpmn-js omits the
	``<bpmn:script>`` tag entirely.  Without this function the compile step
	would fail with:

		AssertionError: Expected 1 result. Received 0 results.

	At runtime FrappeScriptEngine ignores the inline "pass" script when a
	Server Script is configured and calls the Server Script directly instead.
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	try:
		# Register namespace to avoid ns0 prefix noise in output
		_ET.register_namespace("bpmn", BPMN_NS)
		_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
		_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
		_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
		_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

		encoded = bpmn_xml.strip().encode("utf-8")
		root = _ET.fromstring(encoded)

		injected = 0
		for script_task in root.iter(f"{{{BPMN_NS}}}scriptTask"):
			# Check if a <bpmn:script> element already exists
			existing = script_task.findall(f"{{{BPMN_NS}}}script")
			if not existing:
				# Inject a minimal "pass" script as the FIRST child element
				script_elem = _ET.Element(f"{{{BPMN_NS}}}script")
				script_elem.text = "pass  # executed by FrappeScriptEngine (Server Script)"
				script_task.insert(0, script_elem)
				injected += 1

		if injected == 0:
			return bpmn_xml  # nothing to change — return original string

		# Re-serialize preserving the XML declaration (if any)
		xml_bytes = _ET.tostring(root, encoding="unicode", xml_declaration=False)
		if bpmn_xml.strip().startswith("<?xml"):
			# Restore the declaration
			decl_end = bpmn_xml.index("?>") + 2
			return bpmn_xml[:decl_end] + "\n" + xml_bytes
		return xml_bytes

	except Exception:
		# If parsing fails here just return the original — parse_bpmn will surface the real error
		return bpmn_xml


def _validate_workflow_state_field(model, service_extensions: dict) -> None:
	"""
	At deploy time, verify that every doctype referenced in the process model
	has a ``workflow_state`` field when the process depends on workflow state —
	either via a workflow-state start-event trigger or an ``apply_workflow``
	service task.

	Raises ``frappe.ValidationError`` for each doctype missing the field.
	Skips entirely when neither condition is present in the model.
	"""
	has_workflow_state_trigger = any(
		row.workflow_state_condition for row in (model.start_events or [])
	)
	has_apply_workflow_task = any(
		cfg.get("serviceType") == "apply_workflow"
		for cfg in service_extensions.values()
	)

	if not has_workflow_state_trigger and not has_apply_workflow_task:
		return

	# Collect only doctypes involved in workflow operations
	doctypes_to_check = set()

	# Start events that trigger on a specific workflow state
	if has_workflow_state_trigger:
		for row in (model.start_events or []):
			if not row.workflow_state_condition:
				continue
			dt = row.trigger_doctype or model.trigger_doctype
			if dt:
				doctypes_to_check.add(dt)

	# Apply Workflow service tasks — use explicit override or fall back to all context doctypes
	if has_apply_workflow_task:
		for cfg in service_extensions.values():
			if cfg.get("serviceType") != "apply_workflow":
				continue
			target = cfg.get("serviceTargetDoctype")
			if target:
				doctypes_to_check.add(target)
			else:
				if model.trigger_doctype:
					doctypes_to_check.add(model.trigger_doctype)
				for row in (model.target_doctypes or []):
					if row.doctype_name:
						doctypes_to_check.add(row.doctype_name)

	missing = []
	for doctype in sorted(doctypes_to_check):
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			continue  # unknown doctype — let other validations surface it
		if not meta.get_field("workflow_state"):
			missing.append(doctype)

	if not missing:
		return

	error_lines = [_("Workflow State field is missing on: {0}").format(dt) for dt in missing]
	frappe.throw(
		"<br>".join(f"• {line}" for line in error_lines),
		title=_("Missing Workflow State Field"),
	)


@frappe.whitelist()
def compile_process_model(model_name: str) -> dict:
	"""
	Parse the BPMN XML in a Process Model and store the compiled spec.

	Must be called after saving/importing a diagram before any instance
	can be started.  Stores the result in:
		BPMN Process Model.serialized_spec  (main process spec)
		BPMN Process Model.subprocess_specs (call activities / sub-processes)

	Args:
		model_name: Name of the BPMN Process Model

	Returns:
		dict with success, version, subprocess_count
	"""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")

	if not model.bpmn_xml:
		frappe.throw(_("No BPMN XML found in process model '{0}'").format(model_name))

	# ── Always extract the real process_id from the XML ──────────────────────
	# The stored process_id field may be a stale UUID assigned at record-create
	# time, while the BPMN diagram itself uses a different id (e.g. 'Process_1').
	# SpiffWorkflow will fail if the two don't match, so we re-sync here.
	import xml.etree.ElementTree as _ET

	_bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	try:
		_root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
		_process_el = _root.find(f"{{{_bpmn_ns}}}process") or _root.find("process")
		if _process_el is not None:
			xml_process_id = _process_el.get("id", "").strip()
			if xml_process_id and xml_process_id != model.process_id:
				# Sync the field so it always reflects the XML truth
				model.process_id = xml_process_id

			# Block deploy if process is not marked executable in the diagram
			is_executable = _process_el.get("isExecutable", "false").strip().lower()
			if is_executable != "true":
				frappe.throw(
					_("Cannot deploy '{0}': the process is not marked as Executable. "
					  "Open the diagram, select the process (click the pool header or empty canvas), "
					  "and enable the 'Executable' checkbox in the properties panel.").format(model_name),
					title=_("Process Not Executable"),
				)
	except frappe.ValidationError:
		raise  # Re-raise our own validation errors
	except Exception:
		pass  # XML parse errors will surface properly in parse_bpmn() below

	if not model.process_id:
		frappe.throw(
			_("No process_id found in the BPMN XML for '{0}'. Save the Process Map first.").format(model_name)
		)

	from one_bpmn.one_bpmn import engine as bpmn_engine

	# Sanitize XML before parsing
	sanitized_xml = _sanitize_bpmn_xml(model.bpmn_xml)

	# Ensure every ScriptTask has a <bpmn:script> element.
	# SpiffWorkflow REQUIRES a non-empty <bpmn:script> element to parse a
	# scriptTask.  When a designer configures only a Server Script via our
	# properties panel (no inline script), no <bpmn:script> element is written
	# by bpmn-js.  We inject "pass" so SpiffWorkflow parses successfully,
	# and the FrappeScriptEngine will replace it with the configured Server Script.
	sanitized_xml = _ensure_script_task_inline_scripts(sanitized_xml)

	try:
		spec_dict, sp_dict = bpmn_engine.parse_bpmn(
			bpmn_xml=sanitized_xml,
			process_id=model.process_id,
			dmn_xml=model.get("dmn_xml"),
		)
	except Exception as exc:
		frappe.log_error(title="BPMN compile failed", message=frappe.get_traceback())
		frappe.throw(_("Failed to compile BPMN for '{0}': {1}").format(model_name, str(exc)))

	model.serialized_spec = json.dumps(spec_dict)
	model.subprocess_specs = json.dumps(sp_dict)

	# ── Embed all task extensions into the serialized spec in one pass ─────
	# SpiffWorkflow's Python parser ignores custom spiffworkflow:* XML attributes,
	# so we extract them from the BPMN XML now and store them alongside the spec.
	# At runtime, bpmn_process_instance.py reads these to know what each task
	# should actually do (e.g. apply a Frappe workflow state, call a Server Script,
	# resolve user assignments).
	spec_data = json.loads(model.serialized_spec)

	service_extensions = _extract_service_task_config(sanitized_xml)
	if service_extensions:
		spec_data["service_task_extensions"] = service_extensions

	script_extensions = _extract_script_task_config(sanitized_xml)
	if script_extensions:
		spec_data["script_task_extensions"] = script_extensions

	user_extensions = _extract_user_task_config(sanitized_xml)
	if user_extensions:
		spec_data["user_task_extensions"] = user_extensions

	model.serialized_spec = json.dumps(spec_data)

	# ── Validate timer events (enforce minute-level granularity) ──────────
	# Frappe scheduler only runs at minute intervals — reject any timer value
	# that uses seconds (e.g. PT15S, R5/PT10S).
	_validate_timer_granularity(sanitized_xml)

	# ── Extract and populate Start Events child table ─────────────────────
	# Parse all <bpmn:startEvent> elements from the XML and capture their type
	# (None, Conditional, Timer, Signal) and configuration into the child table.
	# Also syncs model-level trigger fields (trigger_type, trigger_doctype,
	# trigger_event) from the BPMN XML so trigger.py can fire instances.
	_populate_start_events(model, sanitized_xml)

	# ── Ensure workflow_state field exists on all reference doctypes ──────
	# When the process uses a workflow-state trigger or apply_workflow service
	# task, every referenced doctype must have the field — create it if absent.
	_validate_workflow_state_field(model, service_extensions)

	# ── Activate this model and manage deployment lifecycle ───────────────
	_activate_deployed_model(model, script_extensions)

	# ── Single save ──────────────────────────────────────────────────────
	# Deploy is allowed even on Production — bypass editability gate
	model.flags.skip_editability_check = True
	model.save(ignore_permissions=True)

	return {
		"success": True,
		"model": model_name,
		"version": model.version,
		"subprocess_count": len(sp_dict),
	}


@frappe.whitelist()
def disable_process_model(model_name: str) -> dict:
	"""
	Disable a deployed BPMN Process Model.

	This is the inverse of ``compile_process_model`` (Deploy).  It:
	1. Sets ``is_active = 0`` — trigger.py will stop creating new instances.
	2. Clears ``serialized_spec`` and ``subprocess_specs`` to prevent
	   stale instantiation.
	3. Disables all Server Scripts linked to this model's script tasks.

	Running instances are NOT affected — they continue to completion with
	their own ``workflow_state``.

	Args:
		model_name: Name of the BPMN Process Model to disable.

	Returns:
		dict with keys ``success`` (bool), ``model`` (str), and
		``running_instances`` (int) — the count of in-flight instances.
	"""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")

	if not model.is_active:
		frappe.throw(
			_("Process map '{0}' is already inactive.").format(model_name),
			title=_("Already Disabled"),
		)

	# ── Deactivate the model ──────────────────────────────────────────────
	model.is_active = 0

	# ── Clear compiled specs (prevents stale instantiation) ───────────────
	# Extract linked scripts BEFORE clearing the spec.
	linked_scripts = _get_linked_server_scripts(model.serialized_spec)
	model.serialized_spec = None
	model.subprocess_specs = None

	# ── Disable linked Server Scripts ─────────────────────────────────────
	for script_name in linked_scripts:
		if frappe.db.exists("Server Script", script_name):
			frappe.db.set_value("Server Script", script_name, "disabled", 1)

	# ── Count running instances (informational) ──────────────────────────
	running_count = frappe.db.count(
		"BPMN Process Instance",
		filters={
			"process_model": model_name,
			"status": ["in", ["Running", "Waiting"]],
		},
	)

	# ── Save — bypass editability gate (same as deploy) ──────────────────
	model.flags.skip_editability_check = True
	model.save(ignore_permissions=True)

	return {
		"success": True,
		"model": model_name,
		"running_instances": running_count,
	}


def _extract_script_task_config(bpmn_xml: str) -> dict:
	"""
	Extract Script Task configuration from BPMN XML at compile time.

	Reads the ``spiffworkflow:serverScript`` attribute from every
	``<bpmn:scriptTask>`` element and returns a dict keyed by BPMN element ID.

	The attribute is written by the BPMN editor as a direct XML attribute on
	the ``<bpmn:scriptTask>`` element, e.g.:

		<bpmn:scriptTask id="Task_1"
			spiffworkflow:serverScript="My Server Script">
		  <bpmn:script>pass</bpmn:script>
		</bpmn:scriptTask>

	Fallback: if no ``spiffworkflow:serverScript`` attribute is set, but the
	inline ``<bpmn:script>`` content looks like a Frappe record name (i.e. it
	does NOT contain Python keywords such as ``=``, ``(``, newlines, etc.), it
	is treated as a Server Script name.  This handles diagrams where the
	designer typed the Server Script name directly into the inline script field
	before the dedicated UI picker existed.

	Embedded at compile time in ``serialized_spec["script_task_extensions"]``.
	"""
	import keyword as _kw
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	def _looks_like_python(text: str) -> bool:
		"""Return True if the text is likely inline Python (not a record name)."""
		if not text:
			return False
		# Heuristics: contains Python-ish characters or keywords
		py_chars = ("=", "(", ")", "{", "}", ":", "\n", ".", "import", "def ", "class ", "return")
		lower = text.strip().lower()
		if any(c in lower for c in py_chars):
			return True
		# Single-word Python keywords (pass, exec, etc.)
		if lower in _kw.kwlist:
			return True
		return False

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except Exception:
		return {}

	extensions = {}
	for elem in root.iter(f"{{{BPMN_NS}}}scriptTask"):
		bpmn_id = elem.get("id", "")
		if not bpmn_id:
			continue

		# ── Primary: spiffworkflow:serverScript attribute ──────────────────────
		server_script = elem.get(f"{{{SPIFF_NS}}}serverScript", "").strip()

		# ── Fallback: inline <bpmn:script> content that is a record name ──────
		if not server_script:
			script_elem = elem.find(f"{{{BPMN_NS}}}script")
			if script_elem is not None and script_elem.text:
				inline = script_elem.text.strip()
				if inline and not _looks_like_python(inline):
					server_script = inline  # treat as Server Script name

		if server_script:
			extensions[bpmn_id] = {"serverScript": server_script}

	return extensions


def _audit_and_notify(doc, actor: str, original_modified=None) -> None:
	"""
	Record the triggering user as modified_by and broadcast a doc_update event.

	Called by service task handlers after every document save, submit, or cancel
	so that:
	  - The ERPNext audit trail (modified_by) shows the user whose action caused
	    the automated change, not "Administrator" or the raw session user.
	  - Any open Frappe desk form for the document auto-reloads via WebSocket.

	When running inside a bpmn_engine_action context the modified timestamp is
	also reverted to original_modified to prevent optimistic-lock conflicts on
	the user's open form (same timestamp-sync workaround as before).
	"""
	if not doc or not doc.doctype or not doc.name:
		return

	actor = actor or frappe.session.user

	if getattr(frappe.flags, "bpmn_engine_action", False) and original_modified:
		# Revert modified timestamp AND record the actor in one DB write
		frappe.db.set_value(
			doc.doctype, doc.name,
			{"modified": original_modified, "modified_by": actor},
			update_modified=False,
		)
		doc.modified = original_modified
		doc.modified_by = actor
	else:
		# Not an engine action — just stamp the actor without touching modified
		frappe.db.set_value(doc.doctype, doc.name, "modified_by", actor, update_modified=False)
		doc.modified_by = actor

	frappe.publish_realtime(
		"doc_update",
		{"modified": str(doc.modified), "modified_by": doc.modified_by},
		doctype=doc.doctype,
		docname=doc.name,
		after_commit=True,
	)


def _apply_docstatus_directly(doc, target_state: str, doc_status_hint: str, actor: str = None) -> None:
	"""
	Fallback used by ``_apply_bpmn_workflow_state`` when the DocType has no
	active Frappe Workflow.

	Behaviour (driven by ``doc_status_hint`` from the BPMN Service Task):
	  "0"  → save as draft (no state change if already submitted)
	  "1"  → submit the document
	  "2"  → cancel the document
	  ""   → save; also set ``workflow_state`` or ``status`` field if it exists

	``target_state`` is set into the first available field from:
	  1. ``workflow_state`` (standard Frappe workflow field)
	  2. ``status`` (common status field on many DocTypes)
	"""
	# ── Determine which field holds the state ─────────────────────────────
	state_field = None
	if target_state:
		meta = frappe.get_meta(doc.doctype)
		if meta.has_field("workflow_state"):
			state_field = "workflow_state"
		elif meta.has_field("status"):
			state_field = "status"

	# Set the state field
	if state_field and target_state:
		doc.set(state_field, target_state)

	ds = str(doc_status_hint).strip()

	original_modified = doc.modified
	if ds == "1":
		if doc.docstatus == 0:
			doc.submit()
		# Already submitted — nothing to do
	elif ds == "2":
		if doc.docstatus == 1:
			doc.cancel()
		# If already cancelled or not submitted — nothing to do
	else:
		# Draft save (ds == "0" or unset)
		if doc.docstatus == 0:
			doc.save(ignore_permissions=True)
		elif doc.docstatus == 1:
			# Submitted doc — just save (amend notes etc.)
			doc.save(ignore_permissions=True)

	_audit_and_notify(doc, actor or frappe.session.user, original_modified)

	if target_state:
		doc.add_comment("Workflow", _(target_state))


def _apply_bpmn_workflow_state(
	doctype: str,
	docname: str,
	target_state: str,
	doc_status_hint: str = "",
	only_allow_role: str = "",
	triggered_by: str = None,
) -> None:
	"""
	Apply a Frappe Workflow state transition to a document.

	This is the backend implementation for the BPMN Service Task
	``serviceType = apply_workflow``.  It mirrors Frappe's own
	``frappe.model.workflow.apply_workflow`` exactly:

	1. Permission check  — ``onlyAllowEdit`` role guard (if configured)
	2. Load fresh doc    — always works from DB to prevent stale data
	3. Workflow lookup   — finds the active Workflow for the DocType
	4. State validation  — verifies the target state exists in the workflow
	5. Transition lookup — finds a valid transition from current → target
	6. Self-approval     — delegates to Frappe's ``has_approval_access``
	7. State + docstatus — calls doc.save / doc.submit / doc.cancel
	8. Workflow comment  — adds a "Workflow" type comment (same as Frappe)

	Args:
		doctype:         The Frappe DocType (e.g. ``Employee Daily Action``)
		docname:         The document name
		target_state:    The workflow state to move to (e.g. ``Submitted``)
		only_allow_role: If non-empty, only users with this role may perform
						 the action (mirrors the Frappe workflow state's
						 ``allow_edit`` field)
		triggered_by:    The user who triggered the BPMN instance
						 (used in place of frappe.session.user when the engine
						 runs in a background worker context)

	Raises:
		frappe.PermissionError  — role check failed
		frappe.ValidationError  — invalid state or illegal docstatus transition
	"""
	from frappe.model.workflow import get_workflow_name, get_workflow, has_approval_access
	from frappe.model.docstatus import DocStatus

	actor = triggered_by or frappe.session.user

	# ── 1. Role guard ─────────────────────────────────────────────────────────
	if only_allow_role and not _is_bpmn_super_user(actor):
		user_roles = frappe.get_roles(actor)
		if only_allow_role not in user_roles:
			frappe.throw(
				_("Only users with the role '{0}' can perform this workflow action.").format(only_allow_role),
				frappe.PermissionError,
			)

	# ── 2. Load fresh doc ─────────────────────────────────────────────────────
	doc = frappe.get_doc(doctype, docname)

	# ── 3. Workflow lookup (graceful — doctype may not have a Frappe Workflow) ─
	# get_workflow_name() returns None when no active Frappe Workflow is
	# configured.  Calling get_workflow(doctype) when no name exists passes
	# None to frappe.get_cached_doc() which raises "Workflow not found".
	# We check the name first to avoid that exception.
	workflow_name = get_workflow_name(doctype)
	workflow = None
	if workflow_name:
		try:
			workflow = get_workflow(doctype)
		except Exception:
			workflow = None

	if not workflow:
		# ── FALLBACK: No Frappe Workflow configured on this DocType ────────────
		# Apply docstatus transition directly (Draft → Submit → Cancel) and
		# optionally set workflow_state / workflow_field if they exist on the doc.
		_apply_docstatus_directly(doc, target_state, doc_status_hint, actor=actor)
		return

	# ── 4. State validation ───────────────────────────────────────────────────
	next_state_row = next((s for s in workflow.states if s.state == target_state), None)
	if not next_state_row:
		frappe.throw(
			_("Workflow state '{0}' not found in Workflow '{1}'.").format(target_state, workflow.name)
		)

	# ── 5. Transition lookup ──────────────────────────────────────────────────
	current_state = doc.get(workflow.workflow_state_field)
	transition = None
	for t in workflow.transitions:
		if t.state == current_state and t.next_state == target_state:
			transition = t
			break

	# If no transition exists AND we're not already in the target state,
	# we cannot move there.
	if transition is None and current_state != target_state:
		frappe.throw(
			_("No valid Workflow transition from '{0}' to '{1}' exists in Workflow '{2}'.").format(
				current_state, target_state, workflow.name
			),
			frappe.ValidationError,
		)

	# ── 6. Self-approval check ────────────────────────────────────────────────
	if transition and not has_approval_access(actor, doc, transition):
		frappe.throw(_("Self approval is not allowed"))

	# ── 7. Apply state + docstatus ────────────────────────────────────────────
	doc.set(workflow.workflow_state_field, target_state)

	if next_state_row.update_field:
		doc.set(next_state_row.update_field, next_state_row.update_value)

	new_docstatus = DocStatus(cint(next_state_row.doc_status or 0))
	# If the BPMN diagram explicitly specifies Document Status, use it as an
	# override (e.g. the state row in Frappe says 0 but the diagram says 1).
	if doc_status_hint in ("0", "1", "2"):
		new_docstatus = DocStatus(cint(doc_status_hint))

	original_modified = doc.modified
	if doc.docstatus.is_draft() and new_docstatus.is_draft():
		doc.save(ignore_permissions=True)
	elif doc.docstatus.is_draft() and new_docstatus.is_submitted():
		from frappe.core.doctype.submission_queue.submission_queue import queue_submission
		from frappe.utils.scheduler import is_scheduler_inactive

		if doc.meta.queue_in_background and not is_scheduler_inactive():
			queue_submission(doc, "Submit")
			return
		doc.submit()
	elif doc.docstatus.is_submitted() and new_docstatus.is_submitted():
		doc.save(ignore_permissions=True)
	elif doc.docstatus.is_submitted() and new_docstatus.is_cancelled():
		doc.cancel()
	elif current_state == target_state:
		# Already in the right state — nothing to do
		return
	else:
		frappe.throw(
			_("Illegal document status transition to state '{0}'.").format(target_state),
			frappe.ValidationError,
		)

	_audit_and_notify(doc, actor, original_modified)

	# ── 8. Workflow comment (same as Frappe's apply_workflow) ─────────────────
	doc.add_comment("Workflow", _(target_state))


@frappe.whitelist()
def start_process(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""
	Create and start a new BPMN Process Instance.

	The engine will immediately run all automated tasks (script tasks,
	gateways, etc.) and pause at the first User Task(s).

	Args:
		model_name:       Name of the BPMN Process Model to run
		context_doctype:  Optional linked Frappe DocType (e.g. 'Work Item')
		context_docname:  Optional linked document name
		initial_data:     Optional JSON string of initial workflow data

	Returns:
		dict with instance name, status, and first active tasks
	"""
	if not model_name:
		frappe.throw(_("model_name is required"))

	if not frappe.db.exists("BPMN Process Model", model_name):
		frappe.throw(_("Process model '{0}' not found").format(model_name))

	parsed_data = {}
	if initial_data:
		parsed_data = frappe.parse_json(initial_data) if isinstance(initial_data, str) else initial_data

	# Create the instance record
	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.status = "Active"
	instance.initiated_by = frappe.session.user
	instance.started_at = frappe.utils.now_datetime()
	if context_doctype:
		instance.context_doctype = context_doctype
	if context_docname:
		instance.context_docname = context_docname
	instance.insert(ignore_permissions=True)

	# Start the engine
	try:
		instance.start(initial_data=parsed_data)
	except Exception as exc:
		# Mark errored and re-raise so the caller knows
		frappe.db.set_value("BPMN Process Instance", instance.name, "status", "Errored")
		frappe.log_error(
			title="BPMN start_process failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(_("Failed to start process '{0}': {1}").format(model_name, str(exc)))

	return {
		"instance": instance.name,
		"status": instance.status,
		"active_tasks": instance.get_active_tasks_summary(),
	}


@frappe.whitelist()
def complete_task(
	instance_name: str,
	task_id: str,
	data: str = None,
) -> dict:
	"""
	Complete a User Task in a running process instance and advance the workflow.

	Performs the same permission and validation checks as Frappe's native
	workflow before allowing the action:
	  1. User assignment check — is the current user assigned to this task?
	  2. Action validation     — is the submitted action in the allowed list?
	  3. Document permission   — does the user have write access to the doc?
	  4. Role check            — does the user have the required role (if any)?

	Args:
		instance_name: Name of the BPMN Process Instance
		task_id:       The SpiffWorkflow task UUID (from active_tasks.task_id)
		data:          Optional JSON string of form data submitted by the user

	Returns:
		dict with updated status and next active tasks
	"""
	if not instance_name or not task_id:
		frappe.throw(_("instance_name and task_id are required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	parsed_data = {}
	if data:
		parsed_data = frappe.parse_json(data) if isinstance(data, str) else data

	# ── Find the active task row ─────────────────────────────────────────────
	active_row = next(
		(r for r in instance.active_tasks if r.task_id == task_id),
		None,
	)
	if not active_row:
		frappe.throw(_("Task '{0}' not found in the active tasks of this instance.").format(task_id))

	if active_row.status != "Waiting":
		frappe.throw(_("Task '{0}' is not in Waiting status.").format(active_row.task_name or task_id))

	current_user = frappe.session.user
	approved_ctc_name = None

	# ── 1. USER ASSIGNMENT CHECK ─────────────────────────────────────────────
	# Same as Frappe's "allow_edit" on workflow states — only the assigned
	# user (or Administrator) can complete the task.
	assigned_user = active_row.assigned_user or ""
	assigned_role = active_row.assigned_role or ""

	if assigned_user and assigned_user != current_user and not _is_bpmn_super_user(current_user):
		# Also allow the document owner (they initiated the process)
		is_doc_owner = False
		if instance.context_doctype and instance.context_docname:
			doc_owner = frappe.db.get_value(instance.context_doctype, instance.context_docname, "owner")
			is_doc_owner = doc_owner == current_user

		if not is_doc_owner:
			# Allow if this specific user has an approved Contingency Task Completion
			# for this context document.  Any other user's CTC does not grant access.
			if instance.context_doctype and instance.context_docname:
				approved_ctc_name = frappe.db.get_value(
					"Contingency Task Completion",
					{
						"context_doctype": instance.context_doctype,
						"context_docname": instance.context_docname,
						"process_owner_user": current_user,
						"status": "Approved",
						"docstatus": 1,
					},
					"name",
				)

			if not approved_ctc_name:
				frappe.throw(
					_("You are not authorized to complete this task. It is assigned to {0}.").format(
						frappe.utils.get_fullname(assigned_user) or assigned_user
					),
					frappe.PermissionError,
				)

	if assigned_role and not _is_bpmn_super_user(current_user):
		user_roles = frappe.get_roles(current_user)
		if assigned_role not in user_roles:
			frappe.throw(
				_("Only users with the role '{0}' can complete this task.").format(assigned_role),
				frappe.PermissionError,
			)

	# ── 2. ACTION VALIDATION ─────────────────────────────────────────────────
	# Same as Frappe's workflow transition validation — the submitted action
	# must be one of the allowed actions configured on the User Task.
	submitted_action = parsed_data.get("action", "")
	allowed_actions_str = active_row.task_actions or ""

	# Parse actions from either JSON array or legacy comma-separated format.
	# New format: [{"action":"Approve","confirmTransition":"true"},{"action":"Reject"}]
	# Legacy format: "Approve,Reject,Send Back"
	_trimmed = allowed_actions_str.strip()
	if _trimmed.startswith("["):
		try:
			_parsed_actions = json.loads(_trimmed)
			allowed_actions = [
				a.get("action", "").strip()
				for a in (_parsed_actions if isinstance(_parsed_actions, list) else [])
				if isinstance(a, dict) and a.get("action", "").strip()
			]
		except (TypeError, ValueError):
			# Invalid JSON — fall back to legacy CSV parsing rather than
			# silently bypassing validation with an empty list.
			frappe.log_error(
				title="BPMN complete_task: malformed task_actions JSON",
				message=f"task_actions={_trimmed!r} on instance {instance_name}",
			)
			allowed_actions = [a.strip() for a in _trimmed.split(",") if a.strip()]
	else:
		allowed_actions = [a.strip() for a in _trimmed.split(",") if a.strip()]

	if allowed_actions:
		if not submitted_action:
			frappe.throw(
				_("An action is required. Valid actions: {0}").format(", ".join(allowed_actions)),
				frappe.ValidationError,
			)
		if submitted_action not in allowed_actions:
			frappe.throw(
				_("Action '{0}' is not allowed. Valid actions: {1}").format(
					submitted_action, ", ".join(allowed_actions)
				),
				frappe.ValidationError,
			)

	# ── 3. DOCUMENT PERMISSION CHECK ─────────────────────────────────────────
	# Same as Frappe's doc.check_permission("write") before workflow action.
	if instance.context_doctype and instance.context_docname:
		if not frappe.has_permission(
			instance.context_doctype, "write", instance.context_docname, user=current_user
		):
			frappe.throw(
				_("You do not have write permission on {0} {1}.").format(
					instance.context_doctype, instance.context_docname
				),
				frappe.PermissionError,
			)

	try:
		active_tasks = instance.advance(task_id=task_id, data=parsed_data)
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
		frappe.log_error(
			title="BPMN complete_task failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(_("Failed to complete task: {0}").format(str(exc)))

	# ── Expire the CTC that authorised this action ───────────────────────────
	if approved_ctc_name:
		frappe.db.set_value("Contingency Task Completion", approved_ctc_name, "status", "Expired")

	# ── Publish realtime events for auto-refresh ────────────────────────────
	# 1. Notify the Processa frontend — broadcast to ALL users so anyone
	#    viewing the instance detail page auto-refreshes.
	#    Note: doc_update for the BPMN Process Instance itself is already
	#    published by Frappe's notify_update() inside run_method("on_update").
	frappe.publish_realtime(
		"bpmn_instance_updated",
		{
			"instance_name": instance_name,
			"status": instance.status,
			"context_doctype": instance.context_doctype or "",
			"context_docname": instance.context_docname or "",
		},
		after_commit=True,
		user="all",
	)

	# 2. Notify the Frappe form of the context document (e.g. Employee Daily
	#    Action) so it auto-refreshes when open in the desk.
	if instance.context_doctype and instance.context_docname:
		frappe.publish_realtime(
			"doc_update",
			{
				"modified": str(frappe.utils.now_datetime()),
				"doctype": instance.context_doctype,
				"name": instance.context_docname,
			},
			doctype=instance.context_doctype,
			docname=instance.context_docname,
			after_commit=True,
		)

	return {
		"instance": instance_name,
		"status": instance.status,
		"active_tasks": active_tasks,
	}


@frappe.whitelist()
def get_instance_tasks(instance_name: str) -> dict:
	"""
	Get the current active tasks and status for a process instance.

	Args:
		instance_name: Name of the BPMN Process Instance

	Returns:
		dict with instance details and waiting tasks
	"""
	if not instance_name:
		frappe.throw(_("instance_name is required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("read")

	return {
		"instance": instance_name,
		"status": instance.status,
		"process_model": instance.process_model,
		"context_doctype": instance.context_doctype,
		"context_docname": instance.context_docname,
		"initiated_by": instance.initiated_by,
		"started_at": str(instance.started_at) if instance.started_at else None,
		"completed_at": str(instance.completed_at) if instance.completed_at else None,
		"active_tasks": instance.get_active_tasks_summary(),
	}


@frappe.whitelist()
def get_instances_for_document(doctype: str, docname: str) -> list:
	"""
	Get all process instances linked to a specific Frappe document.
	Useful for showing workflow history on a Work Item or any other DocType.

	Args:
		doctype: e.g. 'Work Item'
		docname: the document name

	Returns:
		list of instance summaries, most recent first
	"""
	if not doctype or not docname:
		frappe.throw(_("doctype and docname are required"))

	instances = frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": doctype, "context_docname": docname},
		fields=[
			"name",
			"process_model",
			"status",
			"initiated_by",
			"started_at",
			"completed_at",
		],
		order_by="creation desc",
	)

	for inst in instances:
		# Attach current active task names for quick display
		active = frappe.get_all(
			"BPMN Active Task",
			filters={
				"parent": inst.name,
				"parenttype": "BPMN Process Instance",
				"status": "Waiting",
			},
			fields=["task_name", "task_type", "assigned_user"],
		)
		inst["current_tasks"] = active

	return instances


# ============================================================================
# BPMN Form Actions API — used by the global bpmn_form_actions.js injector
# ============================================================================


@frappe.whitelist()
def get_active_bpmn_tasks(doctype: str, docname: str) -> list:
	"""
	Return the currently-waiting User Task actions for a given document.

	Called by bpmn_form_actions.js on every Frappe form refresh to check
	whether this document has a pending BPMN task that the current user
	should act on.  If so, the frontend injects action buttons that look
	identical to Frappe's native workflow action buttons.

	Returns list of dicts:
		instance_name  – BPMN Process Instance name
		task_id        – SpiffWorkflow UUID of the waiting User Task
		task_name      – Human-readable task name
		task_actions   – Comma-separated action labels (e.g. "Submit,Return to Draft")
		assigned_user  – User the task is assigned to (or '' for role-based)
		assigned_role  – Role the task is assigned to (or '')
	"""
	if not doctype or not docname:
		return []

	instance_names = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"context_doctype": doctype,
			"context_docname": docname,
			"status": "Active",
		},
		pluck="name",
	)

	if not instance_names:
		return []

	result = []

	for instance_name in instance_names:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)

			for row in instance.active_tasks:
				if row.status != "Waiting":
					continue

				# Resolve actions — handles both manual and frappe_workflow modes
				actions_str = instance._resolve_task_actions(row)
				actions_detail = instance._resolve_task_actions_detail(row)

				result.append(
					{
						"instance_name": instance_name,
						"task_id": row.task_id,
						"task_name": row.task_name or "",
						"task_actions": actions_str,
						"task_actions_detail": actions_detail,
						"assigned_user": row.assigned_user or "",
						"assigned_role": row.assigned_role or "",
					}
				)

		except Exception:
			frappe.log_error(
				title=f"get_active_bpmn_tasks failed for instance {instance_name}",
				message=frappe.get_traceback(),
			)

	return result


# ============================================================================
# BPMN Message Event API
# ============================================================================


@frappe.whitelist()
def send_message(
	message_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	instance_name: str = None,
	payload: str = None,
) -> dict:
	"""
	Deliver a BPMN message to a running process instance.

	This is the public API for external systems (webhooks, scheduled jobs,
	Server Scripts) to communicate with BPMN processes using the standard
	Message Event pattern.

	Instance lookup:
	    - If ``instance_name`` is provided, deliver directly to that instance.
	    - Otherwise, look up the single active instance for the given
	      ``context_doctype`` + ``context_docname`` pair.

	The message_name must match a ``<bpmn:message name="...">`` defined in
	the process diagram. If no task is waiting for this message, an error
	is raised.

	Convention: message names follow ``{System}: {Event}`` format,
	e.g. ``GitHub: PR Merged``, ``GitHub: PR Changes Requested``.

	Args:
	    message_name:     BPMN message name (required)
	    context_doctype:  DocType of the linked document (e.g. "Work Item")
	    context_docname:  Name of the linked document
	    instance_name:    Direct instance name (overrides context lookup)
	    payload:          JSON string of data to merge into task.data

	Returns:
	    dict with instance status and active tasks
	"""
	if not message_name:
		frappe.throw(_("message_name is required"))

	# ── Resolve the target instance ──────────────────────────────────────
	if not instance_name:
		if not context_doctype or not context_docname:
			frappe.throw(
				_("Either instance_name or both context_doctype and context_docname are required")
			)

		instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": context_doctype,
				"context_docname": context_docname,
				"status": "Active",
			},
			pluck="name",
			limit=1,
		)
		if not instances:
			frappe.throw(
				_('No active BPMN instance found for {0} "{1}"').format(
					context_doctype, context_docname
				)
			)
		instance_name = instances[0]

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	# ── Parse payload ────────────────────────────────────────────────────
	parsed_payload = {}
	if payload:
		parsed_payload = frappe.parse_json(payload) if isinstance(payload, str) else payload

	# ── Deliver message ──────────────────────────────────────────────────
	try:
		active_tasks = instance.receive_message(
			message_name=message_name,
			payload=parsed_payload,
		)
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
		frappe.log_error(
			title="BPMN send_message failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(_("Failed to deliver message: {0}").format(str(exc)))

	# ── Publish realtime events ──────────────────────────────────────────
	frappe.publish_realtime(
		"bpmn_instance_updated",
		{
			"instance_name": instance_name,
			"status": instance.status,
			"context_doctype": instance.context_doctype or "",
			"context_docname": instance.context_docname or "",
		},
		after_commit=True,
		user="all",
	)

	if instance.context_doctype and instance.context_docname:
		frappe.publish_realtime(
			"doc_update",
			{
				"modified": str(frappe.utils.now_datetime()),
				"doctype": instance.context_doctype,
				"name": instance.context_docname,
			},
			doctype=instance.context_doctype,
			docname=instance.context_docname,
			after_commit=True,
		)

	return {
		"instance": instance_name,
		"status": instance.status,
		"active_tasks": active_tasks,
	}


# ============================================================================
# Processa Canvas Comment API
# ============================================================================


@frappe.whitelist()
def get_canvas_comments(model_name: str) -> list:
	"""
	Fetch all comments for a specific BPMN Process Model.
	"""
	if not model_name:
		return []

	comments = frappe.get_list(
		"Comment",
		filters={
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"comment_type": "Comment",
			"is_processa_comment": 1
		},
		fields=[
			"name",
			"reference_name as model",
			"custom_element_id as element_id",
			"content as comment",
			"custom_assigned_to as assigned_to",
			"custom_status as status",
			"owner",
			"custom_is_task as is_task",
			"creation",
		],
		order_by="creation desc",
	)

	if comments:
		user_ids = list(set([c.owner for c in comments] + [c.assigned_to for c in comments if c.assigned_to]))
		user_info = frappe.get_all("User", filters={"name": ["in", user_ids]}, fields=["name", "full_name", "user_image"])
		user_map = {u.name: u for u in user_info}

		# Fetch ToDo statuses and assignees for tasks
		comment_names = [c.name for c in comments if c.is_task]
		todos = {}
		todo_assignees = []
		if comment_names:
			todo_list = frappe.get_all(
				"ToDo", 
				filters={"reference_type": "Comment", "reference_name": ["in", comment_names]}, 
				fields=["reference_name", "status", "allocated_to"]
			)
			for t in todo_list:
				todos[t.reference_name] = {"status": t.status, "allocated_to": t.allocated_to}
				if t.allocated_to:
					todo_assignees.append(t.allocated_to)

		user_ids = list(set([c.owner for c in comments] + [c.assigned_to for c in comments if c.assigned_to] + todo_assignees))
		user_info = frappe.get_all("User", filters={"name": ["in", user_ids]}, fields=["name", "full_name", "user_image"])
		user_map = {u.name: u for u in user_info}

		for c in comments:
			c.author = c.owner  # Legacy alias
			u_info = user_map.get(c.owner, {})
			c.owner_full_name = u_info.get("full_name", c.owner)
			c.owner_image = u_info.get("user_image")
			
			if c.is_task:
				todo_info = todos.get(c.name)
				if todo_info:
					c.status = "Resolved" if todo_info["status"] == "Closed" else todo_info["status"]
					# Use ToDo's allocated_to as the source of truth for assignment
					c.assigned_to = todo_info["allocated_to"]
				else:
					c.status = None
			
			if c.assigned_to:
				a_info = user_map.get(c.assigned_to, {})
				c.assigned_to_full_name = a_info.get("full_name", c.assigned_to)

	return comments


@frappe.whitelist()
def post_canvas_comment(
	model_name: str, element_id: str, comment: str, assigned_to: str = None, is_task: int = 0
) -> dict:
	"""
	Create a new comment on the BPMN canvas using standard Comment DocType.
	"""
	if not model_name or not comment:
		frappe.throw(_("Model name and comment are required"))

	doc = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"content": comment,
			"is_processa_comment": 1,
			"custom_element_id": element_id,
			"custom_assigned_to": assigned_to,
			"custom_is_task": is_task,
			"custom_status": "Open",
		}
	)
	doc.insert(ignore_permissions=True)

	# If assigned to someone, create a ToDo
	if is_task and assigned_to:
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": assigned_to,
				"description": _("BPMN Task for {0}: {1}").format(model_name, comment),
				"reference_type": "Comment",
				"reference_name": doc.name,
			}
		).insert(ignore_permissions=True)

	# --- Notification Logic ---
	recipients = set()
	if assigned_to:
		recipients.add(assigned_to)

	# Extract plain text mentions (@Full Name or @Email)
	# BPMN Editor currently sends mentions as plain text formatted by BpmnEditor.vue
	if "@" in comment:
		active_users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, fields=["name", "full_name"])
		for u in active_users:
			if (u.full_name and f"@{u.full_name}" in comment) or f"@{u.name}" in comment:
				recipients.add(u.name)

	# Exclude author from notifications
	recipients.discard(frappe.session.user)

	if recipients:
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

		# Set type: if it's assigned to someone in the recipients list, use Assignment, else Mention
		notification_type = "Assignment" if assigned_to and assigned_to in recipients else "Mention"
		
		sender_name = frappe.utils.get_fullname(frappe.session.user)
		subject = _("{0} mentioned you on {1}").format(sender_name, model_name)
		if notification_type == "Assignment":
			subject = _("{0} assigned a task to you on {1}").format(sender_name, model_name)
		process_name = frappe.get_value("BPMN Process Model", model_name, "process_name")
		notification_doc = {
			"type": notification_type,
			"document_type": "BPMN Process Model",
			"document_name": model_name,
			"subject": subject,
			"from_user": frappe.session.user,
			"email_content": comment,
			"link": f"/processa/process/{process_name}"
		}
		enqueue_create_notification(list(recipients), notification_doc)

	# Map fields back for frontend compatibility
	res = doc.as_dict()
	res.model = doc.reference_name
	res.element_id = doc.custom_element_id
	res.comment = doc.content
	res.assigned_to = doc.custom_assigned_to
	res.is_task = doc.custom_is_task
	res.status = doc.custom_status
	res.author = doc.owner
	
	return res


@frappe.whitelist()
def update_comment_status(name: str, status: str) -> dict:
	"""
	Update the status of a canvas comment by closing/opening its linked ToDo.
	"""
	if not name or not status:
		frappe.throw(_("Comment name and status are required"))

	allowed_statuses = {"Open", "Resolved", "Closed"}
	normalized_status = status.strip()
	if normalized_status not in allowed_statuses:
		frappe.throw(_("Status must be one of: Open, Resolved, Closed"))

	# Check for linked ToDo
	todo_name = frappe.db.get_value("ToDo", {"reference_type": "Comment", "reference_name": name}, "name")
	if not todo_name:
		frappe.throw(_("No ToDo found linked to this comment. Cannot update status."))

	todo_doc = frappe.get_doc("ToDo", todo_name)
	
	current_user = frappe.session.user
	is_system_manager = "System Manager" in frappe.get_roles(current_user)
	
	allowed_users = {todo_doc.allocated_to, getattr(todo_doc, "assigned_by", None), todo_doc.owner, "Administrator"}
	if current_user not in allowed_users and not is_system_manager:
		frappe.throw(_("Only the assigned user or assigner can update this task's status"))

	todo_status = "Closed" if normalized_status in ("Resolved", "Closed") else "Open"
	
	# Update ToDo
	todo_doc.status = todo_status
	todo_doc.save(ignore_permissions=True)

	# Update Comment custom_status for consistency
	doc = frappe.get_doc("Comment", name)
	doc.custom_status = "Resolved" if todo_status == "Closed" else "Open"
	doc.save(ignore_permissions=True)

	# Map back for frontend compatibility
	res = doc.as_dict()
	res.status = doc.custom_status
	return res


@frappe.whitelist()
def get_users_by_role(role: str) -> list:
	"""
	Fetch all users who have a specific role.
	"""
	if not role:
		return []

	# Get users who have the specified role
	user_list = frappe.get_all("Has Role", filters={"role": role}, fields=["parent as name"])

	user_names = list(set([u.name for u in user_list]))

	if not user_names:
		return []

	return frappe.get_list(
		"User",
		filters={"name": ["in", user_names], "enabled": 1, "user_type": "System User"},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist()
def get_system_users(query: str = "") -> list:
	"""
	Fetch active system users for the @mention autocomplete in the BPMN
	comment dialog. Any authenticated (non-Guest) user may call this.
	When query is empty, returns all active system users (up to limit).
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to fetch system users"))

	normalized_query = (query or "").strip()

	base_filters: list = [
		["User", "enabled", "=", 1],
		["User", "user_type", "=", "System User"],
	]

	if normalized_query:
		# Search both full_name and name (email) — combined safely within the
		# base filter set so enabled/user_type guards always apply.
		base_filters.append([
			"User", "full_name", "like", f"%{normalized_query}%",
			"or",
			"User", "name", "like", f"%{normalized_query}%",
		])

	return frappe.get_list("User",
		filters=base_filters,
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist()
def get_doctype_fields(
	doctype: str,
	search_text: str = "",
	fieldtype_in: str = "",
	fieldtype_not_in: str = "",
	include_options: bool = False,
) -> list:
	"""Return fields for a given DocType.

	Used by the BPMN properties panel to populate field autocompletes.
	Bypasses the parent-permission restriction on the DocField REST API.

	Args:
		doctype: The DocType to fetch fields from.
		search_text: Optional search filter on fieldname.
		fieldtype_in: JSON array of fieldtypes to include (e.g. '["Data","Link"]').
		fieldtype_not_in: JSON array of fieldtypes to exclude.
		include_options: If true, also return the ``options`` column.
	"""
	from frappe.query_builder import DocType as QBDocType

	DocField = QBDocType("DocField")

	select_cols = [DocField.fieldname, DocField.label, DocField.fieldtype]
	if include_options:
		select_cols.append(DocField.options)

	query = (
		frappe.qb.from_(DocField)
		.select(*select_cols)
		.where(DocField.parent == doctype)
		.where(DocField.parenttype == "DocType")
		.orderby(DocField.idx)
		.limit(100)
	)

	if fieldtype_in:
		query = query.where(DocField.fieldtype.isin(json.loads(fieldtype_in)))
	elif fieldtype_not_in:
		query = query.where(DocField.fieldtype.notin(json.loads(fieldtype_not_in)))
	else:
		# Default: exclude layout fields
		query = query.where(
			DocField.fieldtype.notin(
				("Section Break", "Column Break", "Tab Break", "Table")
			)
		)

	if search_text:
		query = query.where(DocField.fieldname.like(f"%{search_text}%"))

	return query.run(as_dict=True)


@frappe.whitelist()
def delete_canvas_element_assets(model_name: str, element_id: str):
	"""
	Delete all comments and associated ToDos linked to a specific BPMN element.
	Called when a shape is deleted from the canvas.
	"""
	if not model_name or not element_id:
		return

	# Find all standard Comment records linked to this specific element
	comments = frappe.get_all("Comment", 
		filters={
			"reference_doctype": "BPMN Process Model", 
			"reference_name": model_name,
			"custom_element_id": element_id,
			"is_processa_comment": 1
		}, 
		fields=["name"]
	)

	for comment in comments:
		# Delete linked ToDos explicitly
		frappe.db.delete("ToDo", {"reference_type": "Comment", "reference_name": comment.name})
		
		# Delete the comment
		frappe.delete_doc("Comment", comment.name, ignore_permissions=True)

	return {"success": True}


@frappe.whitelist()
def cleanup_process_model_assets(model_name: str):
	"""
	Background job to cleanup custom assets when a BPMN Process Model is deleted.
	Updated to support the standard Comment DocType.
	"""
	if not model_name:
		return

	# Find all standard Comment records linked to the model
	comments = frappe.get_all("Comment", 
		filters={
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"is_processa_comment": 1
		}, 
		fields=["name"]
	)

	for comment in comments:
		# Delete linked ToDos
		frappe.db.delete("ToDo", {"reference_type": "Comment", "reference_name": comment.name})

		# Delete the comment
		frappe.delete_doc("Comment", comment.name, ignore_permissions=True)


@frappe.whitelist()
def get_context_doctypes(query: str = None) -> list:
	"""
	Get unique DocTypes used as context in Process Instances, filtered by query.
	Used by the InstanceList filter autocomplete.
	"""
	filters = {}
	if query:
		filters["context_doctype"] = ["like", f"%{query}%"]

	results = frappe.get_all(
		"BPMN Process Instance",
		filters=filters,
		fields=["context_doctype"],
		distinct=True,
		order_by="context_doctype",
		limit=50
	)
	return [{"label": r.context_doctype, "value": r.context_doctype} for r in results if r.context_doctype]


@frappe.whitelist()
def get_context_documents(doctype: str, query: str = None) -> list:
	"""
	Get documents for a specific DocType, filtered by query.
	Used by the InstanceList filter autocomplete.
	"""
	if not doctype:
		return []

	# Use Search Criteria if available, otherwise fallback to name-based filtering
	# get_list respects permissions automatically
	filters = {}
	if query:
		filters["name"] = ["like", f"%{query}%"]

	results = frappe.get_list(
		doctype,
		filters=filters,
		fields=["name"],
		limit=50,
		order_by="modified desc",
	)
	return [{"label": r.name, "value": r.name} for r in results]


# Server Script Version History
# ============================================


@frappe.whitelist()
def get_script_version_history(script_name: str) -> list:
	"""
	Get version history for a Server Script using Frappe's built-in Version tracking.
	Returns a list of versions ordered newest-first.
	"""
	if not script_name:
		return []

	if not frappe.db.exists("Server Script", script_name):
		return []

	frappe.get_doc("Server Script", script_name).check_permission("read")

	current = frappe.db.get_value(
		"Server Script", script_name,
		["modified", "modified_by", "script"],
		as_dict=True
	)

	# Pull version records from Frappe's Version doctype
	version_records = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Server Script", "docname": script_name},
		fields=["name", "creation", "owner", "data"],
		order_by="creation desc",
		limit=100,
	)

	result = []

	# Current (latest) state is always version 1 in the panel
	result.append({
		"version_name": "current",
		"is_current": True,
		"creation": str(current.modified),
		"author": frappe.utils.get_fullname(current.modified_by),
		"description": "Current version",
		"script": current.script or "",
	})

	for record in version_records:
		try:
			data = frappe.parse_json(record.data or "{}")
			changed = data.get("changed", [])
			script_change = next((c for c in changed if c[0] == "script"), None)
			if not script_change:
				continue
			result.append({
				"version_name": record.name,
				"is_current": False,
				"creation": str(record.creation),
				"author": frappe.utils.get_fullname(record.owner),
				"description": "Script updated",
				"script": script_change[1],  # old value before this change
			})
		except Exception:
			pass

	return result


@frappe.whitelist()
def get_script_at_version(version_name: str) -> dict:
	"""
	Get script content at a specific Version record.
	"""
	if version_name == "current":
		return {}

	if not frappe.db.exists("Version", version_name):
		frappe.throw(_("Version record not found."))

	version_doc = frappe.get_doc("Version", version_name)
	data = frappe.parse_json(version_doc.data or "{}")
	changed = data.get("changed", [])
	script_change = next((c for c in changed if c[0] == "script"), None)

	if not script_change:
		return {"script": "# No script changes tracked in this version"}

	return {"script": script_change[1]}


@frappe.whitelist()
def restore_script_version(script_name: str, version_name: str) -> dict:
	"""
	Restore a Server Script to the content stored in a Version record.
	"""
	if not frappe.has_permission("Server Script", "write") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to restore Server Scripts."),
			frappe.PermissionError,
		)

	version_data = get_script_at_version(version_name)
	script_content = version_data.get("script", "")

	return update_server_script(script_name, script_content)
