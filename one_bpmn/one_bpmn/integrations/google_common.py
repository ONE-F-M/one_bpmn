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
import time

import frappe

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
SLIDES_SCOPE = "https://www.googleapis.com/auth/presentations"
DEFAULT_SCOPES = [DRIVE_SCOPE, DOCS_SCOPE, SLIDES_SCOPE]


class GoogleConfigError(Exception):
    """Raised for missing/invalid configuration — not a transient API failure."""


# A Drive/Docs/Slides file id is the token after ``/d/`` in a share link, or the
# value of an ``id=`` query param, or (already) a bare id.
_ID_IN_PATH = re.compile(r"/d/([A-Za-z0-9_-]{10,})")
_ID_IN_QUERY = re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")


def normalize_drive_id(value):
    """Accept a Google share link OR a bare file/folder id and return the id.

    People paste full URLs (``https://docs.google.com/document/d/<id>/edit``,
    ``https://drive.google.com/file/d/<id>/view``, ``...?id=<id>``); the API
    wants just ``<id>``. A value that is already a bare id passes through.
    """
    if not value:
        return value
    s = str(value).strip()
    m = _ID_IN_PATH.search(s) or _ID_IN_QUERY.search(s)
    return m.group(1) if m else s


def load_service_account_info():
    """3-tier lookup: AI Chat Settings singleton → site_config → private/files/gcp.json."""
    sa_json = None
    try:
        sa_json = frappe.get_single("AI Chat Settings").get_password(
            "google_drive_service_account_json", raise_exception=False
        )
    except Exception:
        sa_json = None

    if not sa_json:
        sa_json = frappe.conf.get("google_drive_service_account_json")

    if sa_json:
        return sa_json if isinstance(sa_json, dict) else json.loads(sa_json)

    try:
        with open(frappe.get_site_path("private", "files", "gcp.json")) as f:
            return json.load(f)
    except FileNotFoundError:
        raise GoogleConfigError(
            "No Google service account configured — set it on AI Chat Settings > "
            "Google Drive Settings, or google_drive_service_account_json in "
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
# Google APIs surface transient failures as HTTP 429 (rate limit) and 5xx.
# Retry those a few times with exponential backoff; anything else propagates.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _http_status(exc):
    resp = getattr(exc, "resp", None)  # googleapiclient.errors.HttpError
    if resp is not None:
        try:
            return int(getattr(resp, "status", None))
        except (TypeError, ValueError):
            pass
    return getattr(exc, "status_code", None)


def call_with_retry(fn, *args, attempts=3, base_delay=0.5, **kwargs):
    """Call ``fn(*args, **kwargs)``, retrying transient Google errors.

    Pass the request's bound ``.execute`` so each retry re-issues the call, e.g.
    ``call_with_retry(service.documents().get(documentId=x).execute)``.
    """
    last = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — we re-raise unless transient
            last = exc
            if _http_status(exc) in _TRANSIENT_STATUS and i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
                continue
            raise
    raise last
