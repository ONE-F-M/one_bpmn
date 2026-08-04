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
hand.

THIS IS THE ONLY PLACE THAT STILL KNOWS THE OLD LOCATIONS
---------------------------------------------------------
A migration is allowed to know about the world it is migrating from; runtime
code is not. ``google_common.load_service_account_info`` reads the connector's
Secret and nothing else, so this patch is the last reader of the four historical
locations. ``drop_legacy_google_credential_field`` runs after it and removes
what it leaves behind.

The reads go through ``get_decrypted_password`` against the ``__Auth`` store
rather than a DocField, because by the time post_model_sync patches run the same
migrate has already removed the fields — but the stored secret is still there.
"""

import json

import frappe
from frappe.utils.password import get_decrypted_password

GOOGLE_CONNECTORS = ("google_drive", "google_docs", "google_sheets", "google_slides")

# Where the one global key used to be kept, newest first.
LEGACY_SETTINGS = ("Processa Settings", "AI Chat Settings")


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
	if not legacy and not already:
		print(
			"No Google credential found anywhere. Paste the key on each BPMN "
			"Connector under Authentication > Secret."
		)


def _legacy_key():
	"""The key from wherever it used to live, or None.

	Read from ``__Auth`` by fieldname, not through the DocType's meta: the
	settings fields that used to hold this are gone by the time this runs, while
	the encrypted value they stored is not.
	"""
	for doctype in LEGACY_SETTINGS:
		try:
			value = get_decrypted_password(
				doctype, doctype, "google_drive_service_account_json", raise_exception=False
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
