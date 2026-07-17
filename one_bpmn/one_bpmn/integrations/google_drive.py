# Copyright (c) 2026, one-fm and contributors
# Google Drive integration for Processa document storage (DMS).
#
# Credentials + config live in the "AI Chat Settings" singleton (onefm_mcp) —
# the same settings doc already used for Anthropic/OpenAI/Gemini/Vertex AI/
# Jira/Copilot/Langfuse credentials — under its "Google Drive Settings"
# section:
#   google_drive_service_account_json  - service account JSON (Password field)
#   google_drive_folder_ids            - JSON dict mapping document_type -> Drive folder id, e.g.
#       {"SOP": "<folder id>", "Policy": "<folder id>", "Guideline": "<folder id>",
#        "Manual": "<folder id>", "AI Knowledge Document": "<folder id>"}
#
# Falls back to frappe.conf.get("google_drive_service_account_json") /
# <site>/private/files/gcp.json if the settings doc field is empty, so this
# also works from a bare bench console without the doctype populated.
#
# The backing GCP project must have the Drive API enabled, and the service
# account must be a member of the target Shared Drive (Content Manager or
# above) before any of this actually works — neither of those is something
# this module can do for itself.
#
# Called from Script Tasks (via one_bpmn's Server Script mechanism) — kept as
# plain reusable functions rather than one_bpmn-specific dispatchers, so the
# same functions serve any diagram's Script Task, not just one hardcoded
# BPMN service type.

import io
import json

import frappe

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveConfigError(Exception):
	"""Raised for missing/invalid configuration — not a transient API failure."""


def _get_credentials():
	from google.oauth2 import service_account

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
		sa_info = sa_json if isinstance(sa_json, dict) else json.loads(sa_json)
	else:
		try:
			with open(frappe.get_site_path("private", "files", "gcp.json")) as f:
				sa_info = json.load(f)
		except FileNotFoundError:
			raise GoogleDriveConfigError(
				"No Google Drive service account configured — set it on "
				"AI Chat Settings > Google Drive Settings, or "
				"google_drive_service_account_json in site_config.json, or place "
				"credentials at private/files/gcp.json."
			)
	return service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)


def _get_service():
	from googleapiclient.discovery import build

	return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)


def resolve_folder_id(document_type: str) -> str:
	"""Look up the Drive folder id configured for a given document_type."""
	folder_map = {}
	try:
		raw = frappe.get_single("AI Chat Settings").google_drive_folder_ids
		if raw:
			folder_map = json.loads(raw)
	except Exception:
		folder_map = {}

	if not folder_map:
		folder_map = frappe.conf.get("dms_drive_folder_ids") or {}

	folder_id = folder_map.get(document_type)
	if not folder_id:
		raise GoogleDriveConfigError(
			f"No Drive folder configured for document_type={document_type!r}. "
			f"Set it on AI Chat Settings > Google Drive Settings > Drive Folder IDs "
			f'by Document Type, e.g. {{"SOP": "<folder id>", "Policy": "<folder id>", ...}}.'
		)
	return folder_id


def create_file(
	folder_id: str,
	filename: str,
	content: str,
	target_mime_type: str = "application/vnd.google-apps.document",
	source_mime_type: str = "text/markdown",
) -> dict:
	"""
	Upload ``content`` into ``folder_id``, converting it into a native Google
	Doc (or whatever ``target_mime_type`` is) from ``source_mime_type``.

	Returns the created file's metadata: {"id", "name", "webViewLink"}.
	"""
	from googleapiclient.http import MediaInMemoryUpload

	service = _get_service()
	media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=source_mime_type, resumable=False)
	file_metadata = {
		"name": filename,
		"parents": [folder_id],
		"mimeType": target_mime_type,
	}
	return (
		service.files()
		.create(
			body=file_metadata,
			media_body=media,
			fields="id,name,webViewLink",
			supportsAllDrives=True,
		)
		.execute()
	)


def update_file_content(file_id: str, content: str, source_mime_type: str = "text/markdown") -> dict:
	"""
	Replace an existing file's content — used to push finalized content into
	the empty placeholder file that create_file made earlier, once drafting/
	review is done. Returns the updated file's metadata.
	"""
	from googleapiclient.http import MediaInMemoryUpload

	service = _get_service()
	media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=source_mime_type, resumable=False)
	return (
		service.files()
		.update(fileId=file_id, media_body=media, fields="id,name,webViewLink")
		.execute()
	)


def set_permissions(file_id: str, grants: list) -> list:
	"""
	Apply a list of Drive permission grants to a file.

	Each grant is a dict per the Drive API Permissions resource, e.g.
	  {"type": "domain", "domain": "one-fm.com", "role": "reader"}
	  {"type": "user", "emailAddress": "x@one-fm.com", "role": "writer"}
	"""
	service = _get_service()
	results = []
	for grant in grants:
		results.append(
			service.permissions()
			.create(
				fileId=file_id,
				body=grant,
				fields="id",
				supportsAllDrives=True,
				sendNotificationEmail=False,
			)
			.execute()
		)
	return results


def delete_file(file_id: str, permanent: bool = False) -> None:
	"""
	Remove a file from Drive. Trashes it (recoverable from the Drive trash)
	by default; pass permanent=True to bypass the trash entirely.
	"""
	service = _get_service()
	if permanent:
		service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
	else:
		service.files().update(
			fileId=file_id, body={"trashed": True}, fields="id", supportsAllDrives=True
		).execute()


def list_files(folder_id: str, page_size: int = 20) -> list:
	"""List non-trashed files directly inside a Drive folder."""
	service = _get_service()
	resp = (
		service.files()
		.list(
			q=f"'{folder_id}' in parents and trashed = false",
			fields="files(id,name,mimeType,modifiedTime)",
			pageSize=page_size,
			supportsAllDrives=True,
			includeItemsFromAllDrives=True,
		)
		.execute()
	)
	return resp.get("files", [])


_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _download_raw_bytes(service, file_id: str) -> bytes:
	from googleapiclient.http import MediaIoBaseDownload

	request = service.files().get_media(fileId=file_id)
	buf = io.BytesIO()
	downloader = MediaIoBaseDownload(buf, request)
	done = False
	while not done:
		_, done = downloader.next_chunk()
	return buf.getvalue()


def _extract_pptx_text(raw: bytes) -> str:
	from pptx import Presentation

	prs = Presentation(io.BytesIO(raw))
	blocks = []
	for i, slide in enumerate(prs.slides, start=1):
		lines = [f"## Slide {i}"]
		for shape in slide.shapes:
			if shape.has_text_frame:
				text = shape.text_frame.text.strip()
				if text:
					lines.append(text)
			if shape.has_table:
				for row in shape.table.rows:
					lines.append(" | ".join(cell.text.strip() for cell in row.cells))
		if len(lines) > 1:
			blocks.append("\n".join(lines))
	return "\n\n".join(blocks)


def _extract_docx_text(raw: bytes) -> str:
	from docx import Document as DocxDocument

	doc = DocxDocument(io.BytesIO(raw))
	blocks = [p.text for p in doc.paragraphs if p.text.strip()]
	for table in doc.tables:
		for row in table.rows:
			blocks.append(" | ".join(cell.text.strip() for cell in row.cells))
	return "\n".join(blocks)


def download_file_text(file_id: str, mime_type: str = None) -> str:
	"""
	Fetch a file's text content, converting to plain text regardless of
	source format:
	  - Native Google Docs/Slides   → Drive's own export-to-text API
	  - Raw .pptx (uploaded as-is)  → parsed slide-by-slide via python-pptx
	  - Raw .docx (uploaded as-is)  → parsed paragraph/table via python-docx
	  - Anything else (.md/.txt)    → best-effort UTF-8 decode

	mime_type is looked up from Drive automatically when not supplied —
	pass it explicitly only if the caller already has it on hand (e.g. from
	a prior list_files() call) to save the extra round trip.
	"""
	service = _get_service()
	if mime_type is None:
		mime_type = (
			service.files()
			.get(fileId=file_id, fields="mimeType", supportsAllDrives=True)
			.execute()
			.get("mimeType", "")
		)
	if mime_type in (
		"application/vnd.google-apps.document",
		"application/vnd.google-apps.presentation",
	):
		data = service.files().export(fileId=file_id, mimeType="text/plain").execute()
		return data.decode("utf-8") if isinstance(data, bytes) else data

	raw = _download_raw_bytes(service, file_id)

	if mime_type == _PPTX_MIME:
		return _extract_pptx_text(raw)
	if mime_type == _DOCX_MIME:
		return _extract_docx_text(raw)

	return raw.decode("utf-8", errors="ignore")
