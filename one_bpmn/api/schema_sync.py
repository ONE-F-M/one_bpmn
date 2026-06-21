# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# Production-side sync engine: pulls delta records from the BA site,
# applies them to Production ("BA wins" overwrite), then runs bench migrate.

import subprocess

import frappe
from frappe import _
from frappe.utils import now_datetime


# ─── Internal Helpers ───────────────────────────────────────────────────


def _get_ba_credentials() -> tuple[str, str, str]:
	"""Read BA site credentials from Processa Settings.

	Returns:
		Tuple of (ba_url, api_key, api_secret).

	Raises:
		frappe.ValidationError if credentials are missing.
	"""
	settings = frappe.get_single("Processa Settings")

	if not settings.enable_ba_sync:
		frappe.throw(_("BA Sync is not enabled in Processa Settings."))

	ba_url = (settings.ba_site_url or "").rstrip("/")
	api_key = (settings.get_password("ba_api_key") or "").strip()
	api_secret = (settings.get_password("ba_api_secret") or "").strip()

	if not ba_url or not api_key or not api_secret:
		frappe.throw(
			_("BA site credentials are not fully configured. "
			  "Please go to Processa Settings and fill in the BA Site URL, "
			  "API Key, and API Secret.")
		)

	return ba_url, api_key, api_secret


def _call_ba_api(ba_url: str, api_key: str, api_secret: str, since: str | None) -> dict:
	"""Call the BA site's get_schema_delta endpoint.

	Args:
		ba_url: Base URL of the BA site.
		api_key: API key for authentication.
		api_secret: API secret for authentication.
		since: ISO datetime string for delta filtering, or None for full sync.

	Returns:
		Dict with custom_doctypes, custom_fields, property_setters, sync_timestamp.
	"""
	import requests

	url = f"{ba_url}/api/method/one_bpmn.api.schema_sync_api.get_schema_delta"
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}
	params = {}
	if since:
		params["since"] = since

	try:
		resp = requests.get(url, params=params, headers=headers, timeout=120)
		resp.raise_for_status()
		data = resp.json()
		return data.get("message", data)
	except requests.exceptions.Timeout:
		frappe.throw(_("BA site API request timed out. Please try again."))
	except requests.exceptions.ConnectionError:
		frappe.throw(_("Cannot reach BA site. Please check connectivity and URL."))
	except Exception as e:
		frappe.log_error(
			title="BA Schema Sync API call failed",
			message=f"URL: {url}\nError: {str(e)}",
		)
		frappe.throw(_("Failed to fetch schema delta from BA site: {0}").format(str(e)))




def _apply_custom_field(record: dict, log_doc) -> str:
	"""Apply a single Custom Field record. Returns action taken."""
	name = record.get("name")
	if not name:
		return "Skipped"

	try:
		if frappe.db.exists("Custom Field", name):
			existing = frappe.get_doc("Custom Field", name)
			for key, value in record.items():
				if key in ("doctype", "name", "creation", "modified", "modified_by", "owner"):
					continue
				existing.set(key, value)
			existing.flags.ignore_permissions = True
			existing.flags.ignore_validate = True
			existing.save(ignore_permissions=True)
			return "Updated"
		else:
			new_doc = frappe.get_doc(record)
			new_doc.flags.ignore_permissions = True
			new_doc.flags.ignore_validate = True
			new_doc.insert(ignore_permissions=True)
			return "Created"
	except Exception as e:
		_add_detail_row(
			log_doc,
			record_type="Custom Field",
			record_name=name,
			target_doctype=record.get("dt", ""),
			field_name=record.get("fieldname", ""),
			action="Failed",
			error_message=str(e),
			ba_modified=record.get("modified"),
		)
		raise


def _apply_property_setter(record: dict, log_doc) -> str:
	"""Apply a single Property Setter record. Returns action taken."""
	name = record.get("name")
	if not name:
		return "Skipped"

	try:
		if frappe.db.exists("Property Setter", name):
			existing = frappe.get_doc("Property Setter", name)
			for key, value in record.items():
				if key in ("doctype", "name", "creation", "modified", "modified_by", "owner"):
					continue
				existing.set(key, value)
			existing.flags.ignore_permissions = True
			existing.flags.ignore_validate = True
			existing.save(ignore_permissions=True)
			return "Updated"
		else:
			new_doc = frappe.get_doc(record)
			new_doc.flags.ignore_permissions = True
			new_doc.flags.ignore_validate = True
			new_doc.insert(ignore_permissions=True)
			return "Created"
	except Exception as e:
		_add_detail_row(
			log_doc,
			record_type="Property Setter",
			record_name=name,
			target_doctype=record.get("doc_type", ""),
			field_name=record.get("field_name", ""),
			action="Failed",
			error_message=str(e),
			ba_modified=record.get("modified"),
		)
		raise


def _add_detail_row(
	log_doc,
	record_type: str,
	record_name: str,
	action: str,
	target_doctype: str = "",
	field_name: str = "",
	error_message: str = "",
	ba_modified: str = "",
):
	"""Append a detail row to the Schema Sync Log."""
	log_doc.append("details", {
		"record_type": record_type,
		"record_name": record_name,
		"target_doctype": target_doctype,
		"field_name": field_name,
		"action": action,
		"error_message": error_message,
		"ba_modified": ba_modified,
	})


def _apply_records(log_doc, records: dict) -> tuple[int, int]:
	"""Apply all fetched records to the Production database.

	Uses "BA wins" strategy: if a record exists, overwrite it.

	Args:
		log_doc: The Schema Sync Log document to append details to.
		records: Dict with keys custom_fields, property_setters.

	Returns:
		Tuple of (applied_count, failed_count).
	"""
	settings = frappe.get_single("Processa Settings")
	applied = 0
	failed = 0

	# 1. Custom Fields
	if settings.sync_custom_fields:
		for record in records.get("custom_fields", []):
			try:
				action = _apply_custom_field(record, log_doc)
				_add_detail_row(
					log_doc,
					record_type="Custom Field",
					record_name=record.get("name", ""),
					target_doctype=record.get("dt", ""),
					field_name=record.get("fieldname", ""),
					action=action,
					ba_modified=record.get("modified", ""),
				)
				if action != "Skipped":
					applied += 1
			except Exception:
				failed += 1

	# 3. Property Setters
	if settings.sync_property_setters:
		for record in records.get("property_setters", []):
			try:
				action = _apply_property_setter(record, log_doc)
				_add_detail_row(
					log_doc,
					record_type="Property Setter",
					record_name=record.get("name", ""),
					target_doctype=record.get("doc_type", ""),
					field_name=record.get("field_name", ""),
					action=action,
					ba_modified=record.get("modified", ""),
				)
				if action != "Skipped":
					applied += 1
			except Exception:
				failed += 1

	return applied, failed


def _run_bench_migrate(log_doc) -> bool:
	"""Execute bench migrate via subprocess and capture output.

	Args:
		log_doc: The Schema Sync Log document to update with migration results.

	Returns:
		True if migration succeeded, False otherwise.
	"""
	log_doc.migration_status = "Running"
	log_doc.save(ignore_permissions=True)
	frappe.db.commit()

	try:
		bench_path = frappe.utils.get_bench_path()
		result = subprocess.run(
			["bench", "migrate"],
			cwd=bench_path,
			capture_output=True,
			text=True,
			timeout=600,  # 10 minute timeout
		)

		output = ""
		if result.stdout:
			output += result.stdout
		if result.stderr:
			output += "\n--- STDERR ---\n" + result.stderr

		log_doc.migration_output = output

		if result.returncode == 0:
			log_doc.migration_status = "Success"
			return True
		else:
			log_doc.migration_status = "Failed"
			return False

	except subprocess.TimeoutExpired:
		log_doc.migration_status = "Failed"
		log_doc.migration_output = "bench migrate timed out after 600 seconds."
		return False
	except Exception as e:
		log_doc.migration_status = "Failed"
		log_doc.migration_output = f"Error running bench migrate: {str(e)}"
		return False


# ─── Public API ─────────────────────────────────────────────────────────


def run_schema_sync(sync_type: str = "Scheduled") -> str:
	"""Execute a full schema sync cycle: pull → apply → migrate.

	This is the main entry point called by both the scheduler and
	the manual trigger button.

	Args:
		sync_type: "Scheduled" or "Manual".

	Returns:
		The name of the created Schema Sync Log record.
	"""
	settings = frappe.get_single("Processa Settings")
	if not settings.enable_ba_sync:
		frappe.log_error(
			title="Schema Sync Skipped",
			message="BA Sync is not enabled in Processa Settings.",
		)
		return ""

	# Create the log record
	log_doc = frappe.new_doc("Schema Sync Log")
	log_doc.sync_type = sync_type
	log_doc.status = "In Progress"
	log_doc.started_at = now_datetime()

	# Determine sync window
	since = settings.last_sync_time
	log_doc.sync_window_from = since or ""
	log_doc.sync_window_to = now_datetime()
	log_doc.is_full_sync = 1 if not since else 0

	log_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	try:
		# Step 1: Pull delta from BA
		ba_url, api_key, api_secret = _get_ba_credentials()
		since_str = str(since) if since else None
		records = _call_ba_api(ba_url, api_key, api_secret, since_str)

		total_pulled = (
			len(records.get("custom_fields", []))
			+ len(records.get("property_setters", []))
		)
		log_doc.total_records_pulled = total_pulled

		if total_pulled == 0:
			log_doc.status = "Completed"
			log_doc.completed_at = now_datetime()
			log_doc.migration_status = "Skipped"
			log_doc.migration_output = "No records to sync — migration skipped."
			log_doc.save(ignore_permissions=True)
			frappe.db.commit()
			return log_doc.name

		# Step 2: Apply records
		applied, failed = _apply_records(log_doc, records)
		log_doc.records_applied = applied
		log_doc.records_failed = failed
		log_doc.save(ignore_permissions=True)
		frappe.db.commit()

		# Step 3: Run bench migrate
		if applied > 0:
			migrate_ok = _run_bench_migrate(log_doc)
			# Reload to pick up the modified timestamp that _run_bench_migrate saved
			log_doc.reload()
		else:
			log_doc.migration_status = "Skipped"
			log_doc.migration_output = "No records were applied — migration skipped."
			migrate_ok = True

		# Step 4: Final status
		if failed == 0 and migrate_ok:
			log_doc.status = "Completed"
		elif failed > 0 and applied > 0:
			log_doc.status = "Completed with Errors"
		else:
			log_doc.status = "Failed"

		log_doc.completed_at = now_datetime()
		log_doc.save(ignore_permissions=True)

		# Update last_sync_time on success
		if log_doc.status in ("Completed", "Completed with Errors"):
			# Reload settings to avoid stale modified timestamp
			settings.reload()
			sync_timestamp = records.get("sync_timestamp")
			if sync_timestamp:
				settings.last_sync_time = sync_timestamp
			else:
				settings.last_sync_time = log_doc.sync_window_to
			settings.save(ignore_permissions=True)

		frappe.db.commit()
		return log_doc.name

	except Exception:
		# Reload to avoid stale modified timestamp if a mid-flow save occurred
		try:
			log_doc.reload()
		except Exception:
			pass
		log_doc.status = "Failed"
		log_doc.completed_at = now_datetime()
		log_doc.error_traceback = frappe.get_traceback()
		log_doc.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.log_error(
			title="Schema Sync Failed",
			message=frappe.get_traceback(),
		)
		return log_doc.name


def scheduled_schema_sync():
	"""Entry point for the daily scheduler event.

	Enqueues the sync as a background job to avoid blocking the scheduler.
	"""
	settings = frappe.get_single("Processa Settings")
	if not settings.enable_ba_sync:
		return

	frappe.enqueue(
		method="one_bpmn.api.schema_sync.run_schema_sync",
		queue="long",
		timeout=1500,
		sync_type="Scheduled",
	)


@frappe.whitelist(methods=["POST"])
def trigger_manual_sync() -> dict:
	"""Manually trigger a schema sync from Processa Settings.

	Returns:
		dict with log_name of the created Schema Sync Log.
	"""
	frappe.only_for("System Manager")

	settings = frappe.get_single("Processa Settings")
	if not settings.enable_ba_sync:
		frappe.throw(_("BA Sync is not enabled in Processa Settings."))

	frappe.enqueue(
		method="one_bpmn.api.schema_sync.run_schema_sync",
		queue="long",
		timeout=1500,
		sync_type="Manual",
	)

	return {"status": "queued", "message": _("Schema sync has been queued. Check Schema Sync Log for progress.")}
