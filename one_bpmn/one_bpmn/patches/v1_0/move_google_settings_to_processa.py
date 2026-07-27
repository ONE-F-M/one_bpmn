"""Relocate the Google service-account credential from AI Chat Settings
(onefm_mcp) to Processa Settings (one_bpmn) — the connector credential now lives
in the app that owns the connectors, removing the cross-app read.

Copies the service-account JSON (a Password) using an underlying-storage read
(__Auth), so it works even though the AI Chat Settings DocField is removed by
the same migrate's schema sync (this runs post_model_sync). Idempotent: only
fills Processa Settings when still empty.

The folder map and template file-id fields are intentionally NOT migrated —
folders and templates are entered on the connector element now, not in settings.
"""

import frappe
from frappe.utils.password import get_decrypted_password


def execute():
    if not frappe.db.exists("DocType", "Processa Settings"):
        return

    ps = frappe.get_single("Processa Settings")
    if ps.get_password("google_drive_service_account_json", raise_exception=False):
        return  # already set — nothing to do

    try:
        sa = get_decrypted_password(
            "AI Chat Settings", "AI Chat Settings",
            "google_drive_service_account_json", raise_exception=False,
        )
    except Exception:
        sa = None

    if sa:
        ps.google_drive_service_account_json = sa
        ps.save(ignore_permissions=True)
