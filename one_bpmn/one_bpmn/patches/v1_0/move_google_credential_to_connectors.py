# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Retire the single global Google credential in favour of per-connector keys.

The service account used to live in one place — Processa Settings — and every
Google connector shared it. That made two things impossible: pointing one
connector at a different Google account, and rotating a key for one integration
without affecting the rest.

The key now belongs to the connector that uses it (BPMN Connector →
Authentication → Secret). This patch copies the existing key onto any Google
connector that does not already carry one, so nothing has to be re-entered by
hand, and leaves the old field in place but read-only.

WHY THE OLD FIELD IS NOT DELETED
--------------------------------
Five Server Scripts import the Drive integration directly and know nothing about
connectors. They keep working because the loader falls back to the *Drive
connector's* key when no connector is named — but a site that has not run this
patch, or whose connectors have no key, still needs somewhere to read from.
Removing the field would break those sites silently. It is marked deprecated,
made read-only, and every read of it is logged.

Clear it once every Google connector shows its own Secret.
"""

import json

import frappe

GOOGLE_CONNECTORS = ("google_drive", "google_docs", "google_sheets", "google_slides")


def execute():
	if not frappe.db.table_exists("BPMN Connector"):
		return

	legacy = _legacy_key()
	copied, already = [], []

	for connector_id in GOOGLE_CONNECTORS:
		if not frappe.db.exists("BPMN Connector", connector_id):
			continue
		doc = frappe.get_doc("BPMN Connector", connector_id)
		if doc.get_password("auth_secret", raise_exception=False):
			already.append(connector_id)
			continue
		if not legacy:
			continue
		doc.credential_source = "On this connector"
		doc.auth_secret = legacy
		doc.save(ignore_permissions=True)
		copied.append(connector_id)

	frappe.db.commit()

	if copied:
		print(f"Copied the Google service account onto: {', '.join(copied)}")
	if already:
		print(f"Already had their own key: {', '.join(already)}")
	if legacy and len(already) + len(copied) == len(GOOGLE_CONNECTORS):
		print(
			"Every Google connector now carries its own key. The Processa Settings "
			"field is deprecated and read-only — clear it when you are satisfied."
		)
	elif not legacy and not already:
		print(
			"No Google credential found anywhere. Paste the key on each BPMN "
			"Connector under Authentication > Secret."
		)


def _legacy_key():
	"""The key from wherever it used to live, or None."""
	for doctype in ("Processa Settings", "AI Chat Settings"):
		try:
			value = frappe.get_single(doctype).get_password(
				"google_drive_service_account_json", raise_exception=False
			)
		except Exception:
			value = None
		if value:
			return value

	value = frappe.conf.get("google_drive_service_account_json")
	if value:
		return value if isinstance(value, str) else json.dumps(value)

	try:
		with open(frappe.get_site_path("private", "files", "gcp.json")) as f:
			return f.read()
	except FileNotFoundError:
		return None
