# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json
import time

import frappe
from frappe import _


def _is_onefm_production() -> bool:
	"""Return True if 'Is Production' is checked in OneFM General Setting.

	This is the **highest-priority** editability gate.  When checked, ALL
	process models on this site are unconditionally read-only — even if
	active Pathfinder Logs exist.
	"""
	try:
		return bool(frappe.db.get_single_value("OneFM General Setting", "is_production"))
	except Exception:
		return False


def _is_production_site() -> bool:
	"""Return True if the current Frappe site IS the Production instance.

	Determined by URL comparison: if the current site URL matches the
	``production_url`` configured in Processa Settings, this site is
	considered Production.  Only evaluated when ``connect_to_production``
	is enabled.
	"""
	settings = frappe.get_single("Processa Settings")
	if not settings.connect_to_production:
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
	if settings.connect_to_production:
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

	if settings.connect_to_production:
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

	now = time.time()

	# Clean up expired heartbeats (>45s) and identify others
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


@frappe.whitelist()
def check_process_editable(process_name: str) -> dict:
	"""
	Check if a single process is editable.

	Priority chain (first match wins):
	  1. OneFM General Setting → is_production  →  always read-only
	  2. site_config.json  → bypass_process_lock →  always editable (dev)
	  3. Pathfinder Log check — an active log must exist for the process:
	     a. connect_to_production checked + URL match  →  read-only
	     b. connect_to_production checked  →  check via Production API
	     c. connect_to_production unchecked  →  check locally on same bench

	Args:
		process_name: Name of the Process record.

	Returns:
		dict with editable, pathfinder_log, workflow_state, reason
	"""
	if not process_name:
		frappe.throw(_("Process name is required"))

	# ── Priority 1: OneFM General Setting → is_production ───────────────
	# If this site IS production, ALL processes are unconditionally
	# read-only — Pathfinder Logs are irrelevant.
	if _is_onefm_production():
		return {
			"editable": False,
			"pathfinder_log": None,
			"workflow_state": None,
			"reason": "This is a Production site (OneFM General Setting). Process models are read-only.",
		}

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

	# ── Pathfinder Log check ────────────────────────────────────────────
	# A process is editable only if an active Pathfinder Log exists.
	# HOW we check depends on whether connect_to_production is enabled.
	settings = frappe.get_cached_doc("Processa Settings")

	if settings.connect_to_production:
		# If the current site IS the production URL, always read-only.
		if _is_production_site():
			return {
				"editable": False,
				"pathfinder_log": None,
				"workflow_state": None,
				"reason": "Production site is always read-only.",
			}
		# Check via Production API (remote HTTP or local dev fallback)
		result = _call_production_api(
			"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.is_process_editable",
			{"process_name": process_name},
		)
	else:
		# Check locally on the same bench (Pathfinder Log lives here)
		result = _call_local_pathfinder_api(
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

	Follows the same priority chain as ``check_process_editable``.

	Args:
		process_names: JSON-encoded list of process name strings.

	Returns:
		dict mapping process name → editability info
	"""
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

	# ── Priority 1: OneFM General Setting → is_production ───────────────
	if _is_onefm_production():
		return {
			pname: {
				"editable": False,
				"pathfinder_log": None,
				"workflow_state": None,
				"reason": "This is a Production site (OneFM General Setting). Process models are read-only.",
			}
			for pname in process_names_list
		}

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

	# ── Pathfinder Log check ────────────────────────────────────────────
	settings = frappe.get_cached_doc("Processa Settings")

	if settings.connect_to_production:
		# If the current site IS the production URL, always read-only.
		if _is_production_site():
			return {
				pname: {
					"editable": False,
					"pathfinder_log": None,
					"workflow_state": None,
					"reason": "Production site is always read-only.",
				}
				for pname in process_names_list
			}
		# Check via Production API (remote HTTP or local dev fallback)
		return _call_production_api(
			"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.bulk_check_process_editable",
			{"process_names": json.dumps(process_names_list)},
		)

	# connect_to_production is unchecked — check locally on the same bench
	return _call_local_pathfinder_api(
		"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.bulk_check_process_editable",
		{"process_names": json.dumps(process_names_list)},
	)

