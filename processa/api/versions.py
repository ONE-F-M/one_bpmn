# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt
"""Version history endpoints for process map diagrams and Server Scripts."""

import frappe
from frappe import _

# Saves by the same author within this many minutes share one history group
GROUP_WINDOW_MINUTES = 5


def create_diagram_snapshot(model_name: str, xml_content: str, snapshot_type: str = "auto") -> str | None:
	"""Record the full XML of a diagram save as a BPMN Diagram Version and return its name.

	Auto saves by the same author within GROUP_WINDOW_MINUTES share a group_key. Returns None when nothing changed.
	"""
	if not model_name or not xml_content:
		return None

	process_name = frappe.db.get_value("BPMN Process Model", model_name, "process_name")
	user = frappe.session.user

	last = frappe.get_all(
		"BPMN Diagram Version",
		filters={"model": model_name},
		fields=["name", "owner", "creation", "group_key", "is_named", "bpmn_xml"],
		order_by="creation desc",
		limit=1,
		ignore_permissions=True,  # snapshots are internal; the caller checked the process model
	)

	if last and last[0].bpmn_xml == xml_content:
		return None

	group_key = None
	if snapshot_type == "auto" and last:
		prev = last[0]
		within_window = (
			frappe.utils.time_diff_in_seconds(frappe.utils.now(), prev.creation)
			<= GROUP_WINDOW_MINUTES * 60
		)
		if not prev.is_named and prev.owner == user and within_window:
			group_key = prev.group_key

	if not group_key:
		group_key = frappe.generate_hash(length=12)

	snap = frappe.new_doc("BPMN Diagram Version")
	snap.model = model_name
	snap.process_name = process_name
	snap.bpmn_xml = xml_content
	snap.group_key = group_key
	snap.snapshot_type = snapshot_type
	snap.insert(ignore_permissions=True)  # snapshots are internal; the caller checked the process model

	return snap.name


@frappe.whitelist()
def get_diagram_versions(name: str) -> list:
	"""Return the deployed sibling models (same process_name, version > 0) of a model, newest first.

	The model itself is left out so the user can pick another version to compare against.
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
	"""Return the bpmn_xml and deploy details of the sibling model model_name."""
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


@frappe.whitelist()
def get_edit_history(model_name: str) -> list:
	"""Return a diagram's save snapshots grouped by group_key, newest first.

	A named snapshot is its own group. The first group is flagged is_current.
	"""
	if not model_name:
		frappe.throw(_("Model name is required"))

	doc = frappe.get_doc("BPMN Process Model", model_name)
	doc.check_permission("read")

	snaps = frappe.get_all(
		"BPMN Diagram Version",
		filters={"model": model_name},
		fields=["name", "owner", "creation", "group_key", "is_named", "version_name", "snapshot_type"],
		order_by="creation desc",
		ignore_permissions=True,  # read permission was checked on the process model above
	)

	groups = []
	by_key = {}
	for s in snaps:
		entry = {
			"name": s.name,
			"author": frappe.utils.get_fullname(s.owner) if s.owner else "",
			"author_id": s.owner,
			"timestamp": s.creation,
			"is_named": bool(s.is_named),
			"version_name": s.version_name or "",
			"snapshot_type": s.snapshot_type,
		}

		if s.is_named:
			groups.append({
				"key": s.name,
				"head": s.name,
				"author": entry["author"],
				"author_id": s.owner,
				"timestamp": s.creation,
				"is_named": True,
				"version_name": s.version_name or "",
				"entries": [entry],
			})
			continue

		grp = by_key.get(s.group_key)
		if grp is None:
			grp = {
				"key": s.group_key,
				"head": s.name,
				"author": entry["author"],
				"author_id": s.owner,
				"timestamp": s.creation,
				"is_named": False,
				"version_name": "",
				"entries": [],
			}
			by_key[s.group_key] = grp
			groups.append(grp)
		grp["entries"].append(entry)

	groups.sort(key=lambda g: g["timestamp"], reverse=True)

	if groups:
		groups[0]["is_current"] = True
	for g in groups[1:]:
		g["is_current"] = False

	return groups


@frappe.whitelist()
def get_snapshot_xml(version_name: str) -> dict:
	"""Return the full BPMN XML of one BPMN Diagram Version snapshot."""
	if not version_name:
		frappe.throw(_("Snapshot name is required"))

	snap = frappe.get_doc("BPMN Diagram Version", version_name)
	# Permission is gated on the parent process model
	frappe.get_doc("BPMN Process Model", snap.model).check_permission("read")

	return {
		"name": snap.name,
		"xml_content": snap.bpmn_xml,
		"version_name": snap.version_name or "",
		"author": frappe.utils.get_fullname(snap.owner) if snap.owner else "",
		"timestamp": snap.creation,
	}


@frappe.whitelist()
def name_version(version_name: str, name: str) -> dict:
	"""Name a snapshot so it shows as a pinned version; an empty name demotes it to an auto snapshot."""
	if not version_name:
		frappe.throw(_("Snapshot name is required"))

	snap = frappe.get_doc("BPMN Diagram Version", version_name)
	frappe.get_doc("BPMN Process Model", snap.model).check_permission("write")

	label = (name or "").strip()
	snap.version_name = label
	snap.is_named = 1 if label else 0
	if label and snap.snapshot_type == "auto":
		snap.snapshot_type = "named"
	elif not label and snap.snapshot_type == "named":
		snap.snapshot_type = "auto"
	snap.save(ignore_permissions=True)  # write permission was checked on the process model above

	return {"name": snap.name, "version_name": snap.version_name, "is_named": bool(snap.is_named)}


@frappe.whitelist()
def restore_version(version_name: str) -> dict:
	"""Write a snapshot's XML back onto its process model and record a "restored" snapshot."""
	if not version_name:
		frappe.throw(_("Snapshot name is required"))

	snap = frappe.get_doc("BPMN Diagram Version", version_name)
	model = frappe.get_doc("BPMN Process Model", snap.model)
	model.check_permission("write")

	model.bpmn_xml = snap.bpmn_xml
	model.flags.skip_process_id_regeneration = True
	model.save()

	new_snap = create_diagram_snapshot(model.name, snap.bpmn_xml, snapshot_type="restored")

	return {
		"model_name": model.name,
		"xml_content": snap.bpmn_xml,
		"snapshot": new_snap,
	}


@frappe.whitelist()
def get_script_version_history(script_name: str) -> list:
	"""Return a Server Script's versions from Frappe's Version records, newest first, current state first."""
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

	version_records = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Server Script", "docname": script_name},
		fields=["name", "creation", "owner", "data"],
		order_by="creation desc",
		limit=100,
	)

	result = []

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
	"""Return the script content stored in one Version record."""
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
