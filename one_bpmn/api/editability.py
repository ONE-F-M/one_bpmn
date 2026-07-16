# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json
import time

import frappe
from frappe import _

NOT_EDITABLE_REASON = (
	"No editable Process Implementation. Create a Process Implementation "
	"and move it to the Active state to enable editing."
)

# Source-of-truth methods, executed on the site where the Process
# Implementation records live (Production when connect_to_production is
# enabled, the local site otherwise).
SOURCE_IS_PROCESS_EDITABLE = "one_bpmn.api.editability.is_process_editable"
SOURCE_BULK_CHECK = "one_bpmn.api.editability.bulk_check_process_editable"
SOURCE_IMPLEMENTATIONS_EDITABLE = "one_bpmn.api.editability.check_implementations_editable"


def _is_onefm_production() -> bool:
	"""Return True if 'Is Production' is checked in OneFM General Setting.

	This is the **highest-priority** editability gate.  When checked, ALL
	process models on this site are unconditionally read-only — even if
	editable Process Implementations exist.
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
	settings = frappe.get_cached_doc("Processa Settings")
	if not settings.connect_to_production:
		return False

	production_url = (settings.production_url or "").rstrip("/")
	if not production_url:
		# If production_url is not configured, assume we are NOT production
		# (safe default: allow the editability check to proceed).
		return False
	site_url = frappe.utils.get_url().rstrip("/")
	return site_url == production_url


def _site_lock_override() -> dict | None:
	"""Evaluate the site-wide gates that override per-process checks.

	Returns a response dict when a gate decides editability for the whole
	site (``override: True``), or ``None`` when the per-process
	Process Implementation check should run.

	Priority chain:
	  1. OneFM General Setting → is_production   →  always read-only
	  2. site_config.json → bypass_process_lock  →  always editable (dev)
	  3. Processa Settings → connect_to_production + URL match → read-only
	"""
	if _is_onefm_production():
		return {
			"editable": False,
			"process_implementation": None,
			"workflow_state": None,
			"override": True,
			"reason": "This is a Production site (OneFM General Setting). Process models are read-only.",
		}

	# Local dev bypass — set `"bypass_process_lock": true` in site_config.json
	# to unlock all processes for editing without a Process Implementation.
	if frappe.conf.get("bypass_process_lock"):
		return {
			"editable": True,
			"process_implementation": None,
			"workflow_state": None,
			"override": True,
			"reason": "Local dev mode: bypass_process_lock is enabled in site_config.json.",
		}

	if _is_production_site():
		return {
			"editable": False,
			"process_implementation": None,
			"workflow_state": None,
			"override": True,
			"reason": "Production site is always read-only.",
		}

	return None


def _is_local_dev_mode() -> bool:
	"""Return True when production API credentials are NOT configured.

	In local dev the Process Implementation records live on the same
	bench, so we can call the source API directly without HTTP.
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


def _call_local_api(method_path: str, params: dict) -> dict:
	"""Call a source API method directly (same bench, no HTTP).

	Used when connect_to_production is disabled, and as a fallback in
	local dev when production credentials are not configured.
	"""
	import importlib

	# method_path looks like "one_bpmn.api.editability.is_process_editable"
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
		return _call_local_api(method, params)

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
		# POST (not GET): the payload can be a large JSON list of process names.
		# As a query string it produces a multi-KB URL that nginx/proxies reject
		# with 400 Bad Request. Sending it in the request body avoids the limit.
		resp = requests.post(url, json=params, headers=headers, timeout=10)
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


def _route_to_source(method: str, params: dict) -> dict:
	"""Route a source-of-truth call to where Process Implementations live.

	connect_to_production checked   →  Production API (HTTP, with local
	                                    dev fallback when creds are absent)
	connect_to_production unchecked →  direct call on the same bench
	"""
	settings = frappe.get_cached_doc("Processa Settings")
	if settings.connect_to_production:
		return _call_production_api(method, params)
	return _call_local_api(method, params)


# ─────────────────────────────────────────────────────────────────────────────
# Source-of-truth endpoints — run on the site holding Process Implementations
# (Production when connect_to_production is enabled). These replace the old
# one_fm pathfinder_api endpoints.
# ─────────────────────────────────────────────────────────────────────────────


def _get_editable_implementation_local(process_name: str) -> dict | None:
	"""Most recent editable Process Implementation for a process (local DB).

	A Process Implementation makes its process editable when its workflow
	state is 'Active' and the (auto-managed) 'editable' flag is checked.
	Cancelled documents are ignored.
	"""
	rows = frappe.get_all(
		"Process Implementation",
		filters={
			"process_name": process_name,
			"workflow_state": "Active",
			"editable": 1,
			"docstatus": ["<", 2],
		},
		fields=["name", "workflow_state"],
		order_by="modified desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _format_editability(pi: dict | None) -> dict:
	"""Build a standardised editability response dict."""
	if pi:
		return {
			"editable": True,
			"process_implementation": pi["name"],
			"workflow_state": pi["workflow_state"],
		}
	return {
		"editable": False,
		"process_implementation": None,
		"workflow_state": None,
	}


@frappe.whitelist()
def is_process_editable(process_name: str) -> dict:
	"""
	Check if a process has an editable Process Implementation.

	Called by the BA site (or locally) to determine whether the Processa
	editor should allow editing for a given process.

	A process is editable only if a Process Implementation exists for it
	whose workflow state is 'Active' and whose 'Editable' flag is checked.

	Args:
		process_name: The name of the Process record.

	Returns:
		dict with:
			- editable (bool): True if an editable implementation exists
			- process_implementation (str|None): Name of the most recent one
			- workflow_state (str|None): Its current workflow state
	"""
	if not process_name:
		frappe.throw(_("Process name is required"))

	# Permission check — caller must have read access to both doctypes
	frappe.has_permission("Process", "read", throw=True)
	frappe.has_permission("Process Implementation", "read", throw=True)

	return _format_editability(_get_editable_implementation_local(process_name))


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
	frappe.has_permission("Process Implementation", "read", throw=True)

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
	rows = frappe.get_all(
		"Process Implementation",
		filters={
			"process_name": ["in", process_names],
			"workflow_state": "Active",
			"editable": 1,
			"docstatus": ["<", 2],
		},
		fields=["name", "process_name", "workflow_state"],
		order_by="modified desc",
	)

	# Group by process_name, keeping only the most recent (first) per process
	best_pi_by_process = {}
	for row in rows:
		best_pi_by_process.setdefault(row["process_name"], row)

	return {pname: _format_editability(best_pi_by_process.get(pname)) for pname in process_names}


@frappe.whitelist()
def check_implementations_editable(pi_names: str) -> dict:
	"""
	Check the 'Editable' flag for specific Process Implementations.

	Used for per-model editability: a BPMN Process Model's canvas is only
	editable while the implementation *linked to it* is editable.

	Args:
		pi_names: JSON-encoded list of Process Implementation names.

	Returns:
		dict mapping each implementation name → bool (editable).
	"""
	frappe.has_permission("Process Implementation", "read", throw=True)

	try:
		if isinstance(pi_names, str):
			pi_names = frappe.parse_json(pi_names)
	except Exception:
		frappe.throw(
			_("Invalid pi_names: expected a JSON-encoded list of strings."),
			title=_("Validation Error"),
		)

	if not isinstance(pi_names, list):
		frappe.throw(_("pi_names must be a list"))

	editable = set()
	if pi_names:
		editable = set(
			frappe.get_all(
				"Process Implementation",
				filters={"name": ["in", pi_names], "editable": 1, "docstatus": ["<", 2]},
				pluck="name",
			)
		)
	return {name: name in editable for name in pi_names}


# ─────────────────────────────────────────────────────────────────────────────
# Consumer API — called by the Processa frontend and the BPMN Process Model
# controller. Applies the site-wide gates, then routes the actual Process
# Implementation lookup to the source site.
# ─────────────────────────────────────────────────────────────────────────────


def is_implementation_editable(pi_name: str) -> bool:
	"""Whether a specific Process Implementation is currently editable.

	Routed to Production when connect_to_production is enabled.
	"""
	if not pi_name:
		return False
	result = _route_to_source(
		SOURCE_IMPLEMENTATIONS_EDITABLE, {"pi_names": json.dumps([pi_name])}
	) or {}
	return bool(result.get(pi_name))


def annotate_model_editability(models: list[dict]) -> None:
	"""Set ``implementation_editable`` on each model dict (in place).

	Each dict must carry a ``process_implementation`` key.  A model's canvas
	is editable only when the Process Implementation linked to it has the
	'Editable' field checked (site-wide gates still take precedence).
	"""
	override = _site_lock_override()
	if override is not None:
		for m in models:
			m["implementation_editable"] = override["editable"]
		return

	pi_names = list({m.get("process_implementation") for m in models if m.get("process_implementation")})
	editable_map = {}
	if pi_names:
		editable_map = _route_to_source(
			SOURCE_IMPLEMENTATIONS_EDITABLE, {"pi_names": json.dumps(pi_names)}
		) or {}
	for m in models:
		m["implementation_editable"] = bool(editable_map.get(m.get("process_implementation")))


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
	  3. Process Implementation check — an editable (Active) implementation
	     must exist for the process:
	     a. connect_to_production checked + URL match  →  read-only
	     b. connect_to_production checked  →  check via Production API
	     c. connect_to_production unchecked  →  check locally on same bench

	Args:
		process_name: Name of the Process record.

	Returns:
		dict with editable, process_implementation, workflow_state, override, reason
	"""
	if not process_name:
		frappe.throw(_("Process name is required"))

	override = _site_lock_override()
	if override is not None:
		return override

	result = dict(
		_route_to_source(SOURCE_IS_PROCESS_EDITABLE, {"process_name": process_name}) or {}
	)

	# Add a human-readable reason for the frontend
	result["override"] = False
	if result.get("editable"):
		result["reason"] = f"Editable Process Implementation: {result.get('process_implementation')}"
	else:
		result["reason"] = NOT_EDITABLE_REASON

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

	override = _site_lock_override()
	if override is not None:
		return {pname: dict(override) for pname in process_names_list}

	results = _route_to_source(
		SOURCE_BULK_CHECK, {"process_names": json.dumps(process_names_list)}
	) or {}

	decorated = {}
	for pname in process_names_list:
		info = dict(results.get(pname) or {"editable": False, "process_implementation": None, "workflow_state": None})
		info["override"] = False
		if info.get("editable"):
			info["reason"] = f"Editable Process Implementation: {info.get('process_implementation')}"
		else:
			info["reason"] = NOT_EDITABLE_REASON
		decorated[pname] = info

	return decorated
