# Copyright (c) 2026, one-fm and contributors
"""Credential Alert Recipients becomes a list of Users.

The field on Processa Settings was free text: user ids or email addresses,
comma-separated. It is now a Table MultiSelect of User Group Member rows, so
only real Users can be chosen and nobody can mistype an address into it.

Any site that already holds a text value gets each entry that names a User
turned into a row. Entries that match no User are printed to the migrate log
and dropped; the process owner decided that plain email addresses no longer
belong here. The old text value is cleared afterwards so it cannot be read as
still in force. Idempotent: with no text value there is nothing to do.
"""

import re

import frappe

DOCTYPE = "Processa Settings"
FIELD = "ai_health_alert_recipients"


def migrate_text(text: str) -> tuple[list[str], list[str]]:
	"""Turn the old comma-separated text into rows. Returns (users written,
	entries that matched no User). Existing rows are kept and not duplicated."""
	entries = [e.strip() for e in re.split(r"[,;\n]", text or "") if e.strip()]
	settings = frappe.get_doc(DOCTYPE)
	present = [row.user for row in settings.get(FIELD) or []]
	written, unmatched = [], []
	for entry in entries:
		user = _resolve_user(entry)
		if not user:
			unmatched.append(entry)
			continue
		if user in present or user in written:
			continue
		settings.append(FIELD, {"user": user})
		written.append(user)
	if written:
		settings.save(ignore_permissions=True)
	return written, unmatched


def _resolve_user(entry: str) -> str | None:
	if frappe.db.exists("User", entry):
		return entry
	return frappe.db.get_value("User", {"email": entry}, "name")


def execute():
	text = frappe.db.get_single_value(DOCTYPE, FIELD)
	if not isinstance(text, str) or not text.strip():
		return
	written, unmatched = migrate_text(text)
	# The value lived in tabSingles under the field's name. The field is a
	# table now, so that row is meaningless and is removed rather than left to
	# be mistaken for a setting still in force.
	frappe.db.delete("Singles", {"doctype": DOCTYPE, "field": FIELD})
	print(f"ai_health_recipients_to_users: {len(written)} recipient(s) written as rows: {', '.join(written) or 'none'}")
	if unmatched:
		print(f"ai_health_recipients_to_users: dropped {len(unmatched)} entr(y/ies) that match no User: {', '.join(unmatched)}")
