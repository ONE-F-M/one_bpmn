# Copyright (c) 2026, one-fm and contributors
"""Google credentials, client building and the link-or-id normalizer shared by the Drive, Docs and Slides clients."""

import json
import re

import frappe

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
SLIDES_SCOPE = "https://www.googleapis.com/auth/presentations"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_SCOPES = [DRIVE_SCOPE, DOCS_SCOPE, SLIDES_SCOPE, SHEETS_SCOPE]


class GoogleConfigError(Exception):
	"""Raised for missing or invalid configuration, not a transient API failure."""


# The id after /d/ or /folders/ in a share link, or the value of an id= query param.
_ID_IN_PATH = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]{10,})")
_ID_IN_QUERY = re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")


def normalize_drive_id(value):
	"""Accept a Google share link or a bare file or folder id and return the id."""
	if not value:
		return value
	s = str(value).strip()
	m = _ID_IN_PATH.search(s) or _ID_IN_QUERY.search(s)
	return m.group(1) if m else s


# The connector whose key is used when the caller names none.
_DEFAULT_CONNECTOR = "google_drive"


def _connector_service_account(connector_id):
	"""The key stored on a BPMN Connector, or None when the connector, its table or its Secret is missing."""
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
	"""The service account key from the named connector's Secret, else from the google_drive connector's Secret.

	There is no settings or site_config fallback: each connector's Secret is its whole credential.
	"""
	sa_json = _connector_service_account(connector_id) or _connector_service_account(_DEFAULT_CONNECTOR)
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
			"valid JSON - it must be the whole key file Google issued, not just the "
			f"private key or an API token ({e})."
		) from e


def get_credentials(scopes=None, connector_id=None):
	from google.oauth2 import service_account

	return service_account.Credentials.from_service_account_info(
		load_service_account_info(connector_id), scopes=scopes or DEFAULT_SCOPES
	)


def get_service(api, version, scopes=None, connector_id=None):
	"""Build a googleapiclient service, such as get_service("docs", "v1"), with the connector's own credential."""
	from googleapiclient.discovery import build

	return build(api, version, credentials=get_credentials(scopes, connector_id), cache_discovery=False)
