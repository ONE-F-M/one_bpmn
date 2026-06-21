# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _

# Saves by the same author within this many minutes collapse under one
# history group header (Google-Docs-style grouping to reduce flooding).
GROUP_WINDOW_MINUTES = 5


def create_diagram_snapshot(model_name: str, xml_content: str, snapshot_type: str = "auto") -> str | None:
	"""Record a full-XML snapshot of a diagram save into BPMN Diagram Version.

	Called on every save of a BPMN Process Model. Consecutive saves by the same
	author within ``GROUP_WINDOW_MINUTES`` reuse the previous snapshot's
	``group_key`` so the history panel can collapse them under one header.
	Named snapshots always start (and end) their own group.

	Args:
		model_name: Document name of the BPMN Process Model being saved.
		xml_content: The full BPMN XML at save time.
		snapshot_type: "auto" (autosave), "named" (explicit), or "restored".

	Returns:
		The name of the created snapshot, or None if skipped (no change).
	"""
	if not model_name or not xml_content:
		return None

	process_name = frappe.db.get_value("BPMN Process Model", model_name, "process_name")
	user = frappe.session.user

	# Find the most recent snapshot for this model to decide grouping and to
	# skip pure no-op saves (identical XML).
	last = frappe.get_all(
		"BPMN Diagram Version",
		filters={"model": model_name},
		fields=["name", "owner", "creation", "group_key", "is_named", "bpmn_xml"],
		order_by="creation desc",
		limit=1,
		ignore_permissions=True,
	)

	if last and last[0].bpmn_xml == xml_content:
		# Nothing actually changed since the last snapshot — don't add noise.
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
	snap.insert(ignore_permissions=True)

	return snap.name


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


# ──────────────────────────────────────────────────────────────────────────
# Google-Docs-style edit history (per-save snapshots, grouped)
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_edit_history(model_name: str) -> list:
	"""Return grouped save-history for a diagram, newest first.

	Snapshots sharing a ``group_key`` collapse under one group header (the most
	recent snapshot in the group). Named snapshots are their own single-entry
	group and carry the version name. The very first item is flagged as the
	current version.

	Args:
		model_name: Document name of the BPMN Process Model.

	Returns:
		list of group dicts: {key, name, author, author_id, timestamp,
		is_named, is_current, entries:[{name, author, timestamp, is_named,
		version_name}]}
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

		# Named snapshots never merge — each is its own group.
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

	# Keep groups ordered by their newest entry (snaps are already desc).
	groups.sort(key=lambda g: g["timestamp"], reverse=True)

	if groups:
		groups[0]["is_current"] = True
	for g in groups[1:]:
		g["is_current"] = False

	return groups


@frappe.whitelist()
def get_snapshot_xml(version_name: str) -> dict:
	"""Return the full BPMN XML for a single snapshot.

	Args:
		version_name: Document name of the BPMN Diagram Version snapshot.
	"""
	if not version_name:
		frappe.throw(_("Snapshot name is required"))

	snap = frappe.get_doc("BPMN Diagram Version", version_name)
	# Permission is gated on the parent process model.
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
	"""Name (or rename) a snapshot so it shows as a pinned version.

	Args:
		version_name: Document name of the BPMN Diagram Version snapshot.
		name: Human-readable version name. Empty string clears the name and
			demotes it back to an ordinary auto snapshot.
	"""
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
	snap.save(ignore_permissions=True)

	return {"name": snap.name, "version_name": snap.version_name, "is_named": bool(snap.is_named)}


@frappe.whitelist()
def restore_version(version_name: str) -> dict:
	"""Restore a snapshot's XML back onto its process model as the current diagram.

	Writes the snapshot XML to the BPMN Process Model and records a new
	"restored" snapshot so the restore itself is part of history.

	Args:
		version_name: Document name of the BPMN Diagram Version to restore.
	"""
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
