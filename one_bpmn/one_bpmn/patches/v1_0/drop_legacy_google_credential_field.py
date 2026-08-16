# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Delete the global Google service-account credential.

``move_google_credential_to_connectors`` copied the key onto each Google
connector; the DocType JSON no longer declares the field. Two things still
survive that, because neither is schema:

  * the encrypted value in ``__Auth`` — a Password field's value lives there, so
    removing the DocField orphans the secret rather than deleting it. A copy of a
    live service-account key sitting in a table nothing reads is worth removing
    on its own terms.
  * the ``tabProcessa Settings`` column — Frappe's schema sync adds columns and
    widens them, but never drops one, so it would linger as dead weight holding
    the old ``*****`` placeholder.

REFUSING TO STRAND A SITE
------------------------
A site whose connectors have no key would be left with no credential at all if
this ran blind. So it checks first: if any Google connector still has an empty
Secret while the legacy store holds a key, the key is copied across before
anything is deleted. That is the same thing the previous patch does — repeated
here because this one is destructive and must not depend on the other having
succeeded.
"""

import frappe

LEGACY_FIELD = "google_drive_service_account_json"
LEGACY_SETTINGS = ("Processa Settings", "AI Chat Settings")
GOOGLE_CONNECTORS = ("google_drive", "google_docs", "google_sheets", "google_slides")


def execute():
	legacy = _stored_key()

	if legacy:
		rescued = _backfill_connectors_missing_a_key(legacy)
		if rescued:
			print(f"Copied the legacy Google key onto: {', '.join(rescued)}")

	for doctype in LEGACY_SETTINGS:
		_forget_secret(doctype)

	_drop_column("Processa Settings")

	frappe.db.commit()
	print(
		"Removed the global Google service-account credential. Each connector's "
		"Authentication > Secret is now the only place a key is read from."
	)


def _stored_key():
	"""The orphaned value in ``__Auth``, or None."""
	from frappe.utils.password import get_decrypted_password

	for doctype in LEGACY_SETTINGS:
		try:
			value = get_decrypted_password(doctype, doctype, LEGACY_FIELD, raise_exception=False)
		except Exception:
			value = None
		if value:
			return value
	return None


def _backfill_connectors_missing_a_key(legacy):
	if not frappe.db.table_exists("BPMN Connector"):
		return []

	rescued = []
	for connector_id in GOOGLE_CONNECTORS:
		if not frappe.db.exists("BPMN Connector", connector_id):
			continue
		doc = frappe.get_doc("BPMN Connector", connector_id)
		if doc.get_password("auth_secret", raise_exception=False):
			continue
		doc.credential_source = "On this connector"
		doc.auth_secret = legacy
		doc.save(ignore_permissions=True)
		rescued.append(connector_id)
	return rescued


def _forget_secret(doctype):
	frappe.db.delete("__Auth", {"doctype": doctype, "name": doctype, "fieldname": LEGACY_FIELD})


def _drop_column(doctype):
	table = f"tab{doctype}"
	if not frappe.db.table_exists(doctype):
		return
	columns = [c.name for c in frappe.db.get_table_columns_description(table)]
	if LEGACY_FIELD not in columns:
		return
	frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{LEGACY_FIELD}`")
