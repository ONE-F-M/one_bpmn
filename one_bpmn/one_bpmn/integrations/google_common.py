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


# Where a credential is looked for when the caller names no connector. The Drive
# connector is the de facto default: the Server Scripts that import this module
# directly are all Drive scripts, and every Google connector historically shared
# one key anyway.
_DEFAULT_CONNECTOR = "google_drive"


def _connector_service_account(connector_id):
    """The key stored on a BPMN Connector, or None.

    This is the source of truth. A connector owns its credential, so two of them
    can talk to two different Google accounts — which is the whole reason the
    key moved off a single global setting.
    """
    if not connector_id:
        return None
    try:
        if not frappe.db or not frappe.db.table_exists("BPMN Connector"):
            return None
        if not frappe.db.exists("BPMN Connector", connector_id):
            return None
        secret = frappe.get_cached_doc("BPMN Connector", connector_id).get_password(
            "auth_secret", raise_exception=False
        )
        return secret or None
    except Exception:
        # A credential lookup must never be the thing that breaks a workflow;
        # fall through to the legacy chain and let that report the real problem.
        return None


def load_service_account_info(connector_id=None):
    """Return the service account key, preferring the connector that owns it.

    Order:
      1. the named connector's own Secret
      2. the Drive connector's Secret — for callers with no connector context
         (Script Tasks importing the integration directly)
      3. DEPRECATED: Processa Settings → AI Chat Settings → site_config →
         private/files/gcp.json

    Step 3 exists only so a site that has not yet moved its key keeps working.
    Anything reaching it is logged, because a key there is invisible to the
    connector form and cannot be rotated per connector.
    """
    sa_json = _connector_service_account(connector_id) or _connector_service_account(
        _DEFAULT_CONNECTOR
    )
    if sa_json:
        return sa_json if isinstance(sa_json, dict) else json.loads(sa_json)

    sa_json = _read_setting_secret("google_drive_service_account_json") or frappe.conf.get(
        "google_drive_service_account_json"
    )
    if sa_json:
        _warn_legacy_credential(connector_id, "a settings DocType or site_config")
        return sa_json if isinstance(sa_json, dict) else json.loads(sa_json)

    try:
        with open(frappe.get_site_path("private", "files", "gcp.json")) as f:
            info = json.load(f)
        _warn_legacy_credential(connector_id, "private/files/gcp.json")
        return info
    except FileNotFoundError:
        raise GoogleConfigError(
            "No Google service account configured. Paste the key on the BPMN "
            f"Connector ({connector_id or _DEFAULT_CONNECTOR}) > Authentication > Secret."
        )


def _warn_legacy_credential(connector_id, where):
    """Say so, once per request, when a deprecated location is still in play."""
    flag = "_bpmn_legacy_google_credential_warned"
    if getattr(frappe.flags, flag, False):
        return
    setattr(frappe.flags, flag, True)
    try:
        frappe.logger("connectors").warning(
            f"Google credential came from {where} — deprecated. Paste it on BPMN "
            f"Connector {connector_id or _DEFAULT_CONNECTOR} > Authentication > Secret "
            "so it can be rotated per connector."
        )
    except Exception:
        pass


def get_credentials(scopes=None, connector_id=None):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(
        load_service_account_info(connector_id), scopes=scopes or DEFAULT_SCOPES
    )


def get_service(api, version, scopes=None, connector_id=None):
    """Build a googleapiclient service, e.g. get_service('docs', 'v1').

    ``connector_id`` selects whose credential to use, so a handler runs against
    the account configured on its own connector.
    """
    from googleapiclient.discovery import build

    return build(
        api, version, credentials=get_credentials(scopes, connector_id), cache_discovery=False
    )


# ── Transient-failure retry ─────────────────────────────────────────────────
# The implementation is provider-neutral and lives in integrations/retry.py (the
# connector HTTP executor uses it too). Re-exported here so existing Google
# integrations and Script Tasks that import it from google_common keep working.

from one_bpmn.one_bpmn.integrations.retry import (  # noqa: E402,F401
    _TRANSIENT_STATUS,
    call_with_retry,
)
from one_bpmn.one_bpmn.integrations.retry import http_status as _http_status  # noqa: E402,F401
