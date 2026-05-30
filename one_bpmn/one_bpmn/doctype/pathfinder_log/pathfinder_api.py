# Copyright (c) 2026, ONE FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def _get_active_log_for_process(process_name: str) -> dict | None:
	"""Return the most recent non-Deployed Pathfinder Log for a process.

	Uses ``frappe.get_list`` which respects DocType permissions, so
	callers without read access to Pathfinder Log will receive an empty
	result instead of leaking data.

	Returns:
		A dict with ``name`` and ``status``, or ``None``.
	"""
	logs = frappe.get_list(
		"Pathfinder Log",
		filters={
			"process_name": process_name,
			"status": "Active",
		},
		fields=["name", "status"],
		order_by="modified desc",
		limit_page_length=1,
	)
	return logs[0] if logs else None


def _format_editability(active_log: dict | None) -> dict:
	"""Build a standardised editability response dict."""
	if active_log:
		return {
			"editable": True,
			"pathfinder_log": active_log["name"],
			"status": active_log["status"],
		}
	return {
		"editable": False,
		"pathfinder_log": None,
		"status": None,
	}


@frappe.whitelist()
def is_process_editable(process_name: str) -> dict:
	"""
	Check if a process has an active (non-Deployed) Pathfinder Log.

	Called by the BA site to determine whether the Processa editor
	should allow editing for a given process.

	A process is editable only if there is at least one Pathfinder Log
	linked to it whose status is NOT 'Deployed'.

	Args:
		process_name: The name of the Process record.

	Returns:
		dict with:
			- editable (bool): True if an active Pathfinder Log exists
			- pathfinder_log (str|None): Name of the most recent active log
			- status (str|None): Current status of that log
	"""
	if not process_name:
		frappe.throw(_("Process name is required"))

	# Permission check — caller must have read access to both doctypes
	frappe.has_permission("Process", "read", throw=True)
	frappe.has_permission("Pathfinder Log", "read", throw=True)

	active_log = _get_active_log_for_process(process_name)
	return _format_editability(active_log)


@frappe.whitelist()
def bulk_check_process_editable(process_names: str) -> dict:
	"""
	Batch check editability for multiple processes in a single call.

	Args:
		process_names: JSON-encoded list of process name strings.

	Returns:
		dict mapping each process name to its editability status.
	"""
	# Permission check — caller must have read access to both doctypes
	frappe.has_permission("Process", "read", throw=True)
	frappe.has_permission("Pathfinder Log", "read", throw=True)

	# Safe JSON parsing with validation
	try:
		if isinstance(process_names, str):
			process_names = frappe.parse_json(process_names)
	except Exception:
		frappe.throw(
			_("Invalid process_names: expected a JSON-encoded list of strings."),
			title=_("Validation Error"),
		)

	if not isinstance(process_names, list):
		frappe.throw(_("process_names must be a list"))

	# Single query for all processes — avoids N+1
	all_active_logs = frappe.get_list(
		"Pathfinder Log",
		filters={
			"process_name": ["in", process_names],
			"status": "Active",
		},
		fields=["name", "status", "process_name"],
		order_by="modified desc",
	)

	# Group by process_name, keeping only the most recent (first) per process
	best_log_by_process = {}
	for log in all_active_logs:
		pname = log["process_name"]
		if pname not in best_log_by_process:
			best_log_by_process[pname] = log

	# Build result for every requested process
	result = {}
	for pname in process_names:
		active_log = best_log_by_process.get(pname)
		result[pname] = _format_editability(active_log)

	return result
