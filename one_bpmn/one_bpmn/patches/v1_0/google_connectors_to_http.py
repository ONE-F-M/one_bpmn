# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Move the Google connectors off Python and onto configuration.

The four Google connectors were rows in the DocTypes but every operation still
ran through a Python handler in ``*_ops.py``. Configuration described them;
code executed them. This patch makes the description executable: each operation
that can be expressed as an HTTP call gets its URL, query, body and response
mapping stored on the row, and runs through the declarative executor.

WHAT MAKES THIS POSSIBLE
------------------------
A Google API is ordinary REST — the SDK was only ever buying two things: the
OAuth2 dance, and helpers for binary transfer. The first is now handled by the
``Service Account JSON`` auth type, which mints an access token from the key on
the connector. The second is why some operations stay in Python.

WHAT STAYS IN PYTHON, AND WHY
-----------------------------
Seven operations are not expressible as one HTTP request, and forcing them
would break them:

  createFile, updateFileContent   multipart upload — a request body that is
                                  metadata *and* file bytes together
  downloadText                    downloads binary and parses .docx/.pptx to
                                  text; the parsing is the operation
  appendText, getText (x2)        need a read call, then arithmetic on the
                                  result, then a write
  setPermissions                  one HTTP call per grant, N grants
  revokePermissions               list, then a delete per grant, with rules
                                  about which to skip
  fillTemplate                    builds a request array from a dict and fails
                                  on placeholders that matched nothing

Those keep handlers — but the handler is now named on the row (``handler_path``)
instead of being found by the ``@connector`` registry. Nothing resolves by
implicit lookup any more: every operation says how it runs.

Idempotent, and safe to re-run — it overwrites the execution fields of the
operations it knows about and touches nothing else.
"""

import json

import frappe

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

# Creating a Doc/Sheet/Slides *file* goes through Drive, not the editor API:
# the editor APIs' own create() puts the file in the service account's own
# storage, which has no quota, so it fails with storageQuotaExceeded. Going via
# Drive also lets the caller choose the destination folder.
DRIVE_FILES = f"{DRIVE_API}/files"

CONNECTORS = {
	"google_drive": {
		"base_url": DRIVE_API,
		"scopes": [DRIVE_SCOPE],
	},
	"google_docs": {
		"base_url": "https://docs.googleapis.com/v1",
		"scopes": ["https://www.googleapis.com/auth/documents", DRIVE_SCOPE],
	},
	"google_sheets": {
		"base_url": "https://sheets.googleapis.com/v4",
		"scopes": ["https://www.googleapis.com/auth/spreadsheets", DRIVE_SCOPE],
	},
	"google_slides": {
		"base_url": "https://slides.googleapis.com/v1",
		"scopes": ["https://www.googleapis.com/auth/presentations", DRIVE_SCOPE],
	},
}

# A Drive file-creation body, shared by the three "create a native document"
# operations — they differ only in mimeType.
def _drive_create_body(mime):
	return (
		"{%- set b = {'name': params.title, 'mimeType': '" + mime + "'} -%}"
		"{%- if params.folder %}{% set _ = b.update({'parents': [params.folder]}) %}{% endif -%}"
		"{{ b | tojson }}"
	)


def _BOOL(field):
	"""Render a Boolean field as a real JSON `true`/`false`.

	Jinja has no ``bool`` filter, and a Boolean connector field reaches the
	template as any of "1", "true", True or "" depending on where it came from.
	Writing ``{{ params.x }}`` straight into JSON would emit ``True`` (invalid
	JSON) or the string ``"1"`` (wrong type), so it goes through this.
	"""
	return (
		"{{ 'true' if (params." + field + " | string | lower) in "
		"['1','true','yes','on'] else 'false' }}"
	)


FILE_FIELDS = "id,name,webViewLink"
ALL_DRIVES = {"supportsAllDrives": "true"}

HTTP_OPERATIONS = {
	# ── Drive ───────────────────────────────────────────────────────────────
	("google_drive", "copyFile"): {
		# Shown in the properties panel. There is no API-level guard against
		# following a copy with Update file content, so the warning has to live
		# where the person wiring the diagram will actually read it.
		"description": (
			"Duplicates a document, keeping its design exactly — logos, tables, named "
			"styles, bilingual layout and RTL runs all survive. Use this to instantiate "
			"a branded template, then fill it with Google Docs → Fill template. Do NOT "
			"follow it with Update file content: that replaces the whole body and "
			"destroys the template."
		),
		"http_method": "POST",
		"url_template": "files/{{ params.file }}/copy",
		"query_params_json": {**ALL_DRIVES, "fields": FILE_FIELDS},
		"body_template": (
			"{%- set b = {} -%}"
			"{%- if params.filename %}{% set _ = b.update({'name': params.filename}) %}{% endif -%}"
			"{%- if params.folder %}{% set _ = b.update({'parents': [params.folder]}) %}{% endif -%}"
			"{{ b | tojson }}"
		),
		"response_map_json": {"id": "id", "name": "name", "webViewLink": "webViewLink"},
	},
	("google_drive", "listFiles"): {
		"http_method": "GET",
		"url_template": "files",
		"query_params_json": {
			**ALL_DRIVES,
			"includeItemsFromAllDrives": "true",
			"q": "'{{ params.folder }}' in parents and trashed = false",
			"fields": "files(id,name,mimeType,modifiedTime)",
			"pageSize": "{{ params.pageSize or 20 }}",
		},
		"response_map_json": {"files": "files"},
	},
	("google_drive", "deleteFile"): {
		# Trash, never purge. A service account with Content Manager on a Shared
		# Drive cannot permanently delete — Drive answers 404, not 403, which
		# reads as "missing file" and sends you looking in the wrong place. The
		# `permanent` field is removed rather than silently ignored.
		"http_method": "PATCH",
		"url_template": "files/{{ params.file }}",
		"query_params_json": {**ALL_DRIVES, "fields": "id"},
		"body_template": '{"trashed": true}',
		"response_map_json": {"id": "id"},
	},
	# ── Docs ────────────────────────────────────────────────────────────────
	("google_docs", "createDocument"): {
		"http_method": "POST",
		"url_template": DRIVE_FILES,
		"query_params_json": {**ALL_DRIVES, "fields": FILE_FIELDS},
		"body_template": _drive_create_body("application/vnd.google-apps.document"),
		"response_map_json": {"documentId": "id", "title": "name", "webViewLink": "webViewLink"},
	},
	("google_docs", "insertText"): {
		"http_method": "POST",
		"url_template": "documents/{{ params.document }}:batchUpdate",
		"body_template": (
			"{{ {'requests': [{'insertText': {"
			"'location': {'index': (params.index or 1) | int}, 'text': params.text or ''"
			"}}]} | tojson }}"
		),
		"response_map_json": {"documentId": "documentId"},
	},
	("google_docs", "replaceAllText"): {
		"http_method": "POST",
		"url_template": "documents/{{ params.document }}:batchUpdate",
		"body_template": (
			'{"requests": [{"replaceAllText": {'
			'"containsText": {"text": {{ params.find | tojson }}, "matchCase": ' + _BOOL("matchCase") + '},'
			'"replaceText": {{ (params.replace or "") | tojson }}'
			"}}]}"
		),
		"response_map_json": {
			"documentId": "documentId",
			"occurrencesChanged": "replies[0].replaceAllText.occurrencesChanged",
		},
	},
	# ── Sheets ──────────────────────────────────────────────────────────────
	("google_sheets", "createSpreadsheet"): {
		"http_method": "POST",
		"url_template": DRIVE_FILES,
		"query_params_json": {**ALL_DRIVES, "fields": FILE_FIELDS},
		"body_template": _drive_create_body("application/vnd.google-apps.spreadsheet"),
		"response_map_json": {"spreadsheetId": "id", "title": "name", "webViewLink": "webViewLink"},
	},
	("google_sheets", "getValues"): {
		"http_method": "GET",
		"url_template": "spreadsheets/{{ params.spreadsheet }}/values/{{ params.range }}",
		"response_map_json": {"range": "range", "values": "values"},
	},
	("google_sheets", "updateValues"): {
		"http_method": "PUT",
		"url_template": "spreadsheets/{{ params.spreadsheet }}/values/{{ params.range }}",
		"query_params_json": {"valueInputOption": "{{ params.valueInputOption or 'USER_ENTERED' }}"},
		"body_template": '{"values": {{ params["values"] }}}',
		"response_map_json": {"updatedCells": "updatedCells", "updatedRange": "updatedRange"},
	},
	("google_sheets", "appendValues"): {
		"http_method": "POST",
		"url_template": "spreadsheets/{{ params.spreadsheet }}/values/{{ params.range or 'A1' }}:append",
		"query_params_json": {
			"valueInputOption": "{{ params.valueInputOption or 'USER_ENTERED' }}",
			"insertDataOption": "INSERT_ROWS",
		},
		"body_template": '{"values": {{ params["values"] }}}',
		"response_map_json": {"updatedRange": "updates.updatedRange", "updatedCells": "updates.updatedCells"},
	},
	("google_sheets", "clearValues"): {
		"http_method": "POST",
		"url_template": "spreadsheets/{{ params.spreadsheet }}/values/{{ params.range }}:clear",
		"body_template": "{}",
		"response_map_json": {"clearedRange": "clearedRange"},
	},
	("google_sheets", "addSheet"): {
		"http_method": "POST",
		"url_template": "spreadsheets/{{ params.spreadsheet }}:batchUpdate",
		"body_template": (
			"{{ {'requests': [{'addSheet': {'properties': {'title': params.title}}}]} | tojson }}"
		),
		"response_map_json": {
			"sheetId": "replies[0].addSheet.properties.sheetId",
			"title": "replies[0].addSheet.properties.title",
		},
	},
	# ── Slides ──────────────────────────────────────────────────────────────
	("google_slides", "createPresentation"): {
		"http_method": "POST",
		"url_template": DRIVE_FILES,
		"query_params_json": {**ALL_DRIVES, "fields": FILE_FIELDS},
		"body_template": _drive_create_body("application/vnd.google-apps.presentation"),
		"response_map_json": {"presentationId": "id", "title": "name", "webViewLink": "webViewLink"},
	},
	("google_slides", "createSlide"): {
		"http_method": "POST",
		"url_template": "presentations/{{ params.presentation }}:batchUpdate",
		"body_template": (
			"{%- set r = {} -%}"
			"{%- if params.layout %}{% set _ = r.update("
			"{'slideLayoutReference': {'predefinedLayout': params.layout}}) %}{% endif -%}"
			"{{ {'requests': [{'createSlide': r}]} | tojson }}"
		),
		"response_map_json": {"slideObjectId": "replies[0].createSlide.objectId"},
	},
	("google_slides", "duplicateSlide"): {
		"http_method": "POST",
		"url_template": "presentations/{{ params.presentation }}:batchUpdate",
		"body_template": (
			"{{ {'requests': [{'duplicateObject': "
			"{'objectId': params.slideObjectId}}]} | tojson }}"
		),
		"response_map_json": {"slideObjectId": "replies[0].duplicateObject.objectId"},
	},
	("google_slides", "replaceAllText"): {
		"http_method": "POST",
		"url_template": "presentations/{{ params.presentation }}:batchUpdate",
		"body_template": (
			'{"requests": [{"replaceAllText": {'
			'"containsText": {"text": {{ params.find | tojson }}, "matchCase": ' + _BOOL("matchCase") + '},'
			'"replaceText": {{ (params.replace or "") | tojson }}'
			"}}]}"
		),
		"response_map_json": {"occurrencesChanged": "replies[0].replaceAllText.occurrencesChanged"},
	},
}

# The operations the API's own shape keeps in Python. Named explicitly on the
# row so nothing resolves by implicit registry lookup.
PYTHON_OPERATIONS = {
	("google_drive", "createFile"): "one_bpmn.one_bpmn.connectors.google_drive_ops.create_file",
	("google_drive", "updateFileContent"): "one_bpmn.one_bpmn.connectors.google_drive_ops.update_file_content",
	("google_drive", "downloadText"): "one_bpmn.one_bpmn.connectors.google_drive_ops.download_text",
	("google_drive", "setPermissions"): "one_bpmn.one_bpmn.connectors.google_drive_ops.set_permissions",
	("google_drive", "revokePermissions"): "one_bpmn.one_bpmn.connectors.google_drive_ops.revoke_permissions",
	("google_docs", "appendText"): "one_bpmn.one_bpmn.connectors.google_docs_ops.append_text",
	("google_docs", "getText"): "one_bpmn.one_bpmn.connectors.google_docs_ops.get_text",
	("google_docs", "fillTemplate"): "one_bpmn.one_bpmn.connectors.google_docs_ops.fill_template",
	("google_slides", "getText"): "one_bpmn.one_bpmn.connectors.google_slides_ops.get_text",
}


def execute():
	if not frappe.db.table_exists("BPMN Connector"):
		return

	service_account = _existing_service_account()
	for connector_id, cfg in CONNECTORS.items():
		if not frappe.db.exists("BPMN Connector", connector_id):
			continue
		_configure_connector(connector_id, cfg, service_account)

	for (connector_id, operation), cfg in HTTP_OPERATIONS.items():
		_apply(connector_id, operation, execution_type="HTTP Request", handler_path="", **cfg)

	for (connector_id, operation), handler in PYTHON_OPERATIONS.items():
		_apply(connector_id, operation, execution_type="Python Handler", handler_path=handler)

	_drop_permanent_delete_field()

	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()
	frappe.db.commit()
	print(
		f"Google connectors: {len(HTTP_OPERATIONS)} operations now run as configured HTTP "
		f"requests, {len(PYTHON_OPERATIONS)} keep a named Python handler"
	)


def _existing_service_account():
	"""The key already in use, so nothing has to be re-entered by hand.

	Read through the same loader the Python handlers use, so whichever of the
	four historical locations holds it (Processa Settings, AI Chat Settings,
	site_config, gcp.json) is picked up.
	"""
	try:
		from one_bpmn.one_bpmn.integrations.google_common import load_service_account_info

		info = load_service_account_info()
		return json.dumps(info) if isinstance(info, dict) else info
	except Exception:
		# A site with no Google credentials configured is a normal state — the
		# connectors are still converted, they just have no key yet.
		return None


def _configure_connector(connector_id, cfg, service_account):
	doc = frappe.get_doc("BPMN Connector", connector_id)
	doc.execution_type = "HTTP Request"
	doc.base_url = cfg["base_url"]
	doc.auth_type = "Service Account JSON"
	doc.auth_scopes = "\n".join(cfg["scopes"])

	# Copy the key onto the connector so each one owns its own credential and can
	# be pointed at a different Google account later. Only when it is not already
	# set, so re-running never overwrites a key someone has since changed.
	if service_account and not doc.get_password("auth_secret", raise_exception=False):
		doc.credential_source = "On this connector"
		doc.auth_secret = service_account

	doc.save(ignore_permissions=True)


def _apply(connector_id, operation, **values):
	name = frappe.db.get_value(
		"BPMN Connector Operation", {"connector": connector_id, "operation_id": operation}, "name"
	)
	if not name:
		return
	doc = frappe.get_doc("BPMN Connector Operation", name)
	for field, value in values.items():
		# The JSON-typed columns hold text; dicts are stored formatted so the
		# form stays readable for whoever edits them next.
		doc.set(field, json.dumps(value, indent=2) if isinstance(value, dict) else value)
	doc.save(ignore_permissions=True)


def _drop_permanent_delete_field():
	"""deleteFile no longer offers `permanent` — see the note on the operation."""
	name = frappe.db.get_value(
		"BPMN Connector Operation", {"connector": "google_drive", "operation_id": "deleteFile"}, "name"
	)
	if not name:
		return
	doc = frappe.get_doc("BPMN Connector Operation", name)
	keep = [f for f in doc.fields if f.field_name != "permanent"]
	if len(keep) != len(doc.fields):
		doc.fields = keep
		doc.save(ignore_permissions=True)
