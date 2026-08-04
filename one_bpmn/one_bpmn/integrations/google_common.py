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


# Where a credential is looked for when the caller names no connector. The Drive
# connector is the de facto default: the Server Scripts that import this module
# directly are all Drive scripts, and every Google connector historically shared
# one key anyway.
_DEFAULT_CONNECTOR = "google_drive"


def _connector_service_account(connector_id):
    """The key stored on a BPMN Connector, or None.

    Raises nothing: a missing connector, a missing table and an empty Secret are
    all "no key here", and the caller turns that into one actionable error.
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
        return None


def load_service_account_info(connector_id=None):
    """Return the service account key from the connector that owns it.

    Order:
      1. the named connector's own Secret
      2. the Drive connector's Secret — for callers with no connector context
         (Script Tasks importing the integration directly)

    There is deliberately no third step. A connector's Secret is the whole
    definition of its credential: that is what makes two connectors able to talk
    to two different Google accounts, and what makes rotating one key a single
    edit on one form. Every global fallback that used to sit behind this
    (Processa Settings, AI Chat Settings, ``site_config.json``,
    ``private/files/gcp.json``) held a key that no connector form could show and
    no one could rotate per connector, so a site could look correctly configured
    while every connector quietly shared one account. Reading them is now an
    error that names the form to fix.
    """
    sa_json = _connector_service_account(connector_id) or _connector_service_account(
        _DEFAULT_CONNECTOR
    )
    if not sa_json:
        raise GoogleConfigError(
            "No Google service account configured for connector "
            f"{connector_id or _DEFAULT_CONNECTOR}. Paste the key file Google issued "
            f"on BPMN Connector {connector_id or _DEFAULT_CONNECTOR} > Authentication "
            "> Secret."
        )
    if isinstance(sa_json, dict):
        return sa_json
    try:
        return json.loads(sa_json)
    except ValueError as e:
        raise GoogleConfigError(
            f"The Secret on BPMN Connector {connector_id or _DEFAULT_CONNECTOR} is not "
            "valid JSON — it must be the whole key file Google issued, not just the "
            f"private key or an API token ({e})."
        ) from e


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
