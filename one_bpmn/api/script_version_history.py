# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _


# ============================================
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

	from one_bpmn.api.server_script_api import update_server_script
	return update_server_script(script_name, script_content)
