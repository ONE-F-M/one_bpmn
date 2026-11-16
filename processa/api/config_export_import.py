# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import now

from processa.utils.session import as_user

# Export key, DocType. Tools before skills before configurations: each links to the one before it.
AGENT_RECORD_SETS = (
	("agent_tools", "AI Agent Tool"),
	("ai_skills", "AI Skill"),
	("agent_configurations", "AI Agent Configuration"),
)
AGENT_DOCTYPES = {doctype for _key, doctype in AGENT_RECORD_SETS}


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

	from processa.processa_engine.maps.references import extract_bpmn_references

	refs = extract_bpmn_references(xml_content)
	agent_records = _agent_records(refs["agent_configurations"])
	tool_scripts = {tool["script"] for tool in agent_records["agent_tools"] if tool.get("script")}

	# ── Collect Server Scripts ────────────────────────────────────────────
	server_scripts = []
	for script_name in sorted(refs["server_scripts"] | tool_scripts):
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
		**agent_records,
		"counts": {
			"server_scripts": len(server_scripts),
			"workflow_states": len(workflow_states),
			"workflow_action_masters": len(workflow_action_masters),
			**{key: len(records) for key, records in agent_records.items()},
		},
	}


def _agent_records(agent_names: set) -> dict:
	"""The referenced agent configurations with their child tables, plus the skills and tools they link to."""
	configurations, skills, tools = [], [], []
	skill_names, tool_names = set(), set()
	for name in sorted(agent_names):
		if not frappe.db.exists("AI Agent Configuration", name):
			continue
		doc = frappe.get_doc("AI Agent Configuration", name)
		configurations.append(_record_payload(doc))
		skill_names.update(row.skill for row in doc.enabled_skills if row.skill)
	for name in sorted(skill_names):
		if not frappe.db.exists("AI Skill", name):
			continue
		doc = frappe.get_doc("AI Skill", name)
		skills.append(_record_payload(doc))
		tool_names.update(row.tool for row in doc.allowed_tools if row.tool)
	for name in sorted(tool_names):
		if frappe.db.exists("AI Agent Tool", name):
			tools.append(_record_payload(frappe.get_doc("AI Agent Tool", name)))
	return {"agent_configurations": configurations, "ai_skills": skills, "agent_tools": tools}


def _record_payload(doc) -> dict:
	"""The document's own fields and child rows, without the metadata a site stamps on them."""
	data = doc.as_dict(no_default_fields=True, no_child_table_fields=True, no_private_properties=True)
	data["name"] = doc.name
	return json.loads(frappe.as_json(data))


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
	failed = []

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

		with as_user("Administrator"):
			doc.insert(ignore_permissions=True)

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

		with as_user("Administrator"):
			doc.insert(ignore_permissions=True)

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

			with as_user("Administrator"):
				doc.insert(ignore_permissions=True)

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

	# Import agent tools, skills and configurations
	for key, doctype in AGENT_RECORD_SETS:
		for data in config.get(key, []):
			_import_agent_record(doctype, data, created, skipped, needs_confirmation, failed)

	frappe.db.commit()

	return {
		"created": created,
		"skipped": skipped,
		"needs_confirmation": needs_confirmation,
		"failed": failed,
	}


def _import_agent_record(
	doctype: str, data: dict, created: list, skipped: list, needs_confirmation: list, failed: list
):
	"""Create a missing record, skip an identical one, or queue a changed one for the user's decision."""
	name = data.get("name", "")
	if not name:
		return
	incoming = {k: v for k, v in data.items() if k != "name"}
	if frappe.db.exists(doctype, name):
		existing = _record_payload(frappe.get_doc(doctype, name))
		existing.pop("name", None)
		if existing == incoming:
			skipped.append({"name": name, "type": doctype})
			return
		needs_confirmation.append({
			"name": name,
			"type": doctype,
			"existing_text": json.dumps(existing, indent=2, sort_keys=True),
			"incoming_text": json.dumps(incoming, indent=2, sort_keys=True),
			"incoming_data": data,
		})
		return
	frappe.db.savepoint("config_import_record")
	try:
		_write_agent_record(doctype, name, incoming, is_new=True)
	except (frappe.ValidationError, frappe.LinkValidationError, frappe.MandatoryError) as exc:
		# A record that cannot be saved here (a model or user the site lacks) is reported, not dropped silently.
		frappe.db.rollback(save_point="config_import_record")
		failed.append({"name": name, "type": doctype, "reason": str(exc)})
		return
	created.append({"name": name, "type": doctype})


def _write_agent_record(doctype: str, name: str, fields: dict, is_new: bool):
	"""Insert or overwrite one agent record from its payload; child tables are replaced whole."""
	if is_new:
		doc = frappe.new_doc(doctype)
		doc.__newname = name
	else:
		doc = frappe.get_doc(doctype, name)
	doc.update(fields)
	# in_import skips the agent's provider credential re-check and mutes Notifications and Webhooks for this save.
	previous = frappe.flags.in_import
	frappe.flags.in_import = True
	try:
		with as_user("Administrator"):
			if is_new:
				doc.insert(ignore_permissions=True)  # the import runs as Administrator, like the script import above
			else:
				doc.save(ignore_permissions=True)  # confirm_overwrite_config checked the caller's write access first
	finally:
		frappe.flags.in_import = previous


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

		with as_user("Administrator"):
			doc = frappe.get_doc("Server Script", name)
			doc.script = script
			doc.disabled = 0
			doc.save(ignore_permissions=True)

		updated.append({"name": name, "type": "Server Script"})

	frappe.db.commit()

	return {"updated": updated}


@frappe.whitelist(methods=["POST"])
def confirm_overwrite_config(overwrites: str) -> dict:
	"""Overwrite agent tools, skills or configurations the user confirmed in the import dialog.

	overwrites: JSON list of objects with doctype, name and data (the exported record).
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		items = json.loads(overwrites) if isinstance(overwrites, str) else overwrites
	except (json.JSONDecodeError, ValueError):
		frappe.throw(_("Invalid overwrites data"))

	is_manager = "System Manager" in frappe.get_roles()
	updated = []
	for item in items:
		doctype = item.get("doctype", "")
		name = item.get("name", "")
		if doctype not in AGENT_DOCTYPES:
			frappe.throw(_("{0} cannot be overwritten from a config file.").format(doctype or _("This record")))
		if not is_manager and not frappe.has_permission(doctype, "write"):
			frappe.throw(
				_("You need write access to {0} or the System Manager role to overwrite it.").format(doctype),
				frappe.PermissionError,
			)
		if not name or not frappe.db.exists(doctype, name):
			continue
		fields = {k: v for k, v in (item.get("data") or {}).items() if k != "name"}
		_write_agent_record(doctype, name, fields, is_new=False)
		updated.append({"name": name, "type": doctype})

	frappe.db.commit()

	return {"updated": updated}
