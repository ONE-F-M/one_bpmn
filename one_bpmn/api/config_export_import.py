# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import now


# ============================================
# Configuration Export / Import API
#
# Exports and imports Server Scripts, Workflow States, and Workflow Action
# Masters referenced by a BPMN process model.  Used to synchronise these
# configuration records between environments (e.g. BA site → Production).
# ============================================


@frappe.whitelist()
def export_bpmn_config(xml_content: str) -> dict:
	"""
	Given BPMN XML, extract all referenced Server Scripts, Workflow States,
	and Workflow Action Masters, and return their full data for download.

	Args:
		xml_content: Raw BPMN XML text

	Returns:
		dict with export_metadata, server_scripts, workflow_states,
		workflow_action_masters, and counts for each category
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	from one_bpmn.api.process_map_api import _extract_bpmn_references

	refs = _extract_bpmn_references(xml_content)

	# ── Collect Server Scripts ────────────────────────────────────────────
	server_scripts = []
	for script_name in sorted(refs["server_scripts"]):
		if not frappe.db.exists("Server Script", script_name):
			continue
		doc = frappe.get_doc("Server Script", script_name)
		server_scripts.append({
			"name": doc.name,
			"script_type": doc.script_type,
			"reference_doctype": doc.reference_doctype or "",
			"doctype_event": doc.doctype_event or "",
			"script": doc.script or "",
			"api_method": doc.api_method or "",
			"allow_guest": doc.allow_guest or 0,
			"event_frequency": doc.event_frequency or "",
			"cron_format": doc.cron_format or "",
			"module": doc.module or "",
			"disabled": doc.disabled or 0,
		})

	# ── Collect Workflow States ───────────────────────────────────────────
	workflow_states = []
	for state_name in sorted(refs["workflow_states"]):
		if not frappe.db.exists("Workflow State", state_name):
			continue
		doc = frappe.get_doc("Workflow State", state_name)
		workflow_states.append({
			"name": doc.name,
			"workflow_state_name": doc.workflow_state_name or doc.name,
			"style": doc.style or "",
			"icon": doc.icon or "",
		})

	# ── Collect Workflow Action Masters ───────────────────────────────────
	workflow_action_masters = []
	for action_label in sorted(refs["workflow_actions"]):
		existing = frappe.db.get_value(
			"Workflow Action Master",
			{"workflow_action_name": action_label},
			["name", "workflow_action_name"],
			as_dict=True,
		)
		if not existing:
			continue
		workflow_action_masters.append({
			"name": existing.name,
			"workflow_action_name": existing.workflow_action_name,
		})

	return {
		"export_metadata": {
			"source_site": frappe.local.site,
			"export_date": now(),
			"exported_by": frappe.session.user,
			"version": "1.0",
		},
		"server_scripts": server_scripts,
		"workflow_states": workflow_states,
		"workflow_action_masters": workflow_action_masters,
		"counts": {
			"server_scripts": len(server_scripts),
			"workflow_states": len(workflow_states),
			"workflow_action_masters": len(workflow_action_masters),
		},
	}


@frappe.whitelist()
def import_bpmn_config(config_json: str) -> dict:
	"""
	Import configuration records from a JSON payload.

	For each record type:
	  - Workflow States & Action Masters: create if missing, skip if exists.
	  - Server Scripts: create if missing, skip if identical, flag if modified.

	Args:
		config_json: JSON string with server_scripts, workflow_states,
		             and workflow_action_masters arrays

	Returns:
		dict with created, skipped, and needs_confirmation lists
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		config = json.loads(config_json) if isinstance(config_json, str) else config_json
	except (json.JSONDecodeError, ValueError):
		frappe.throw(_("Invalid JSON configuration data"))

	created = []
	skipped = []
	needs_confirmation = []

	# ── Import Workflow States ────────────────────────────────────────────
	for ws_data in config.get("workflow_states", []):
		name = ws_data.get("name", "")
		if not name:
			continue

		if frappe.db.exists("Workflow State", name):
			skipped.append({"name": name, "type": "Workflow State"})
			continue

		doc = frappe.new_doc("Workflow State")
		doc.__newname = name
		doc.workflow_state_name = ws_data.get("workflow_state_name", name)
		doc.style = ws_data.get("style", "")
		if ws_data.get("icon"):
			doc.icon = ws_data["icon"]

		original_user = frappe.session.user
		try:
			frappe.set_user("Administrator")
			doc.insert(ignore_permissions=True)
		finally:
			frappe.set_user(original_user)

		created.append({"name": name, "type": "Workflow State"})

	# ── Import Workflow Action Masters ────────────────────────────────────
	for wa_data in config.get("workflow_action_masters", []):
		action_name = wa_data.get("workflow_action_name", "")
		if not action_name:
			continue

		if frappe.db.exists("Workflow Action Master", {"workflow_action_name": action_name}):
			skipped.append({"name": action_name, "type": "Workflow Action Master"})
			continue

		doc = frappe.new_doc("Workflow Action Master")
		doc.workflow_action_name = action_name

		original_user = frappe.session.user
		try:
			frappe.set_user("Administrator")
			doc.insert(ignore_permissions=True)
		finally:
			frappe.set_user(original_user)

		created.append({"name": action_name, "type": "Workflow Action Master"})

	# ── Import Server Scripts ─────────────────────────────────────────────
	for ss_data in config.get("server_scripts", []):
		name = ss_data.get("name", "")
		if not name:
			continue

		if not frappe.db.exists("Server Script", name):
			# Missing → create immediately
			doc = frappe.new_doc("Server Script")
			doc.__newname = name
			doc.script_type = ss_data.get("script_type", "API")
			doc.script = ss_data.get("script", "")
			doc.reference_doctype = ss_data.get("reference_doctype", "")
			doc.doctype_event = ss_data.get("doctype_event", "")
			doc.api_method = ss_data.get("api_method", "")
			doc.allow_guest = ss_data.get("allow_guest", 0)
			doc.event_frequency = ss_data.get("event_frequency", "")
			doc.cron_format = ss_data.get("cron_format", "")
			doc.module = ss_data.get("module", "")
			doc.disabled = 0

			original_user = frappe.session.user
			try:
				frappe.set_user("Administrator")
				doc.insert(ignore_permissions=True)
			finally:
				frappe.set_user(original_user)

			created.append({"name": name, "type": "Server Script"})
		else:
			# Exists → compare script content
			existing_doc = frappe.get_doc("Server Script", name)
			incoming_script = ss_data.get("script", "")
			existing_script = existing_doc.script or ""

			if incoming_script.strip() == existing_script.strip():
				skipped.append({"name": name, "type": "Server Script"})
			else:
				needs_confirmation.append({
					"name": name,
					"type": "Server Script",
					"existing_script": existing_script,
					"incoming_script": incoming_script,
				})

	frappe.db.commit()

	return {
		"created": created,
		"skipped": skipped,
		"needs_confirmation": needs_confirmation,
	}


@frappe.whitelist()
def confirm_overwrite_scripts(overwrites: str) -> dict:
	"""
	Overwrite Server Scripts that the user has explicitly confirmed.

	Args:
		overwrites: JSON string — list of objects with "name" and "script" keys

	Returns:
		dict with updated list
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	if not frappe.has_permission("Server Script", "write") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to overwrite Server Scripts."),
			frappe.PermissionError,
		)

	try:
		items = json.loads(overwrites) if isinstance(overwrites, str) else overwrites
	except (json.JSONDecodeError, ValueError):
		frappe.throw(_("Invalid overwrites data"))

	updated = []
	for item in items:
		name = item.get("name", "")
		script = item.get("script", "")
		if not name or not frappe.db.exists("Server Script", name):
			continue

		original_user = frappe.session.user
		try:
			frappe.set_user("Administrator")
			doc = frappe.get_doc("Server Script", name)
			doc.script = script
			doc.disabled = 0
			doc.save(ignore_permissions=True)
		finally:
			frappe.set_user(original_user)

		updated.append({"name": name, "type": "Server Script"})

	frappe.db.commit()

	return {"updated": updated}
