# Copyright (c) 2026, one-fm and contributors
# Shared Google API plumbing for the BPMN connector layer.
#
# Additive on purpose: google_drive.py keeps its own self-contained credential
# loader (and GoogleDriveConfigError) so the existing Script Task server scripts
# continue to work untouched during the connector migration. This module is the
# shared base for the connector handlers and the future Docs/Slides integrations,
# plus the link-or-ID normalizer used by every Drive-file/-folder field.

import json
import re

import frappe

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
SLIDES_SCOPE = "https://www.googleapis.com/auth/presentations"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_SCOPES = [DRIVE_SCOPE, DOCS_SCOPE, SLIDES_SCOPE, SHEETS_SCOPE]


class GoogleConfigError(Exception):
    """Raised for missing/invalid configuration — not a transient API failure."""


# A Drive/Docs/Slides id is the token after ``/d/`` (files/docs/slides) or
# ``/folders/`` (folders) in a share link, or the value of an ``id=`` query
# param, or (already) a bare id.
_ID_IN_PATH = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]{10,})")
_ID_IN_QUERY = re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")


def normalize_drive_id(value):
    """Accept a Google share link OR a bare file/folder id and return the id.

    People paste full URLs (``https://docs.google.com/document/d/<id>/edit``,
    ``https://drive.google.com/file/d/<id>/view``,
    ``https://drive.google.com/drive/folders/<id>``, ``...?id=<id>``); the API
    wants just ``<id>``. A value that is already a bare id passes through.
    """
    if not value:
        return value
    s = str(value).strip()
    m = _ID_IN_PATH.search(s) or _ID_IN_QUERY.search(s)
    return m.group(1) if m else s


# Google config now lives on Processa Settings (this app). AI Chat Settings is
# kept as a read fallback for sites that configured it there before the move.
_SETTINGS_DOCTYPES = ("Processa Settings", "AI Chat Settings")


def _read_setting_secret(fieldname):
    for doctype in _SETTINGS_DOCTYPES:
        try:
            val = frappe.get_single(doctype).get_password(fieldname, raise_exception=False)
        except Exception:
            val = None
        if val:
            return val
    return None


def load_service_account_info():
    """Lookup order: Processa Settings → AI Chat Settings → site_config → gcp.json."""
    sa_json = _read_setting_secret("google_drive_service_account_json")

    if not sa_json:
        sa_json = frappe.conf.get("google_drive_service_account_json")

    if sa_json:
        return sa_json if isinstance(sa_json, dict) else json.loads(sa_json)

    try:
        with open(frappe.get_site_path("private", "files", "gcp.json")) as f:
            return json.load(f)
    except FileNotFoundError:
        raise GoogleConfigError(
            "No Google service account configured — set it on Processa Settings > "
            "Google Integration, or google_drive_service_account_json in "
            "site_config.json, or place credentials at private/files/gcp.json."
        )


def get_credentials(scopes=None):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(
        load_service_account_info(), scopes=scopes or DEFAULT_SCOPES
    )


def get_service(api, version, scopes=None):
    """Build a googleapiclient service, e.g. get_service('docs', 'v1')."""
    from googleapiclient.discovery import build

    return build(api, version, credentials=get_credentials(scopes), cache_discovery=False)


# ── Transient-failure retry ─────────────────────────────────────────────────
# The implementation is provider-neutral and lives in integrations/retry.py (the
# connector HTTP executor uses it too). Re-exported here so existing Google
# integrations and Script Tasks that import it from google_common keep working.

from one_bpmn.one_bpmn.integrations.retry import (  # noqa: E402,F401
    _TRANSIENT_STATUS,
    call_with_retry,
)
from one_bpmn.one_bpmn.integrations.retry import http_status as _http_status  # noqa: E402,F401
