# Copyright (c) 2026, one-fm and contributors
"""Google Drive client for Processa document storage, authenticated with the google_drive connector's Secret."""

import io

from processa.processa_connectors.google import common as gc


class GoogleDriveConfigError(Exception):
	"""Raised for missing or invalid configuration, not a transient API failure."""


def _get_service(connector_id="google_drive"):
	"""Drive client authenticated as the connector's own service account; Server Scripts catch GoogleDriveConfigError."""
	try:
		return gc.get_service("drive", "v3", scopes=[gc.DRIVE_SCOPE], connector_id=connector_id)
	except gc.GoogleConfigError as e:
		raise GoogleDriveConfigError(str(e)) from e


# The read and share functions take an optional service so a caller with another Google identity can reuse them.


def create_file(
	folder_id: str,
	filename: str,
	content: str,
	target_mime_type: str = "application/vnd.google-apps.document",
	source_mime_type: str = "text/markdown",
) -> dict:
	"""Upload content into folder_id, converting it from source_mime_type to target_mime_type.

	Returns the created file's id, name and webViewLink.
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
	"""Replace an existing file's content and return its id, name and webViewLink."""
	from googleapiclient.http import MediaInMemoryUpload

	service = _get_service()
	media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=source_mime_type, resumable=False)
	return (
		service.files()
		.update(fileId=file_id, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True)
		.execute()
	)


def set_permissions(file_id: str, grants: list, service=None) -> list:
	"""Apply Drive Permissions resources to a file.

	A user grant is an upsert on the email's direct grant; other grant types are always created.
	"""
	service = service or _get_service()
	results = []
	existing = None
	for grant in grants:
		if grant.get("type") == "user" and grant.get("emailAddress"):
			if existing is None:
				existing = _direct_user_grants(service, file_id)
			current = existing.get(grant["emailAddress"].lower())
			if current:
				results.append(
					service.permissions()
					.update(
						fileId=file_id,
						permissionId=current["id"],
						body={"role": grant["role"]},
						fields="id,role",
						supportsAllDrives=True,
					)
					.execute()
				)
				continue
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


def _direct_user_grants(service, file_id: str) -> dict:
	"""Map lower-cased email -> permission for user grants held directly on the file."""
	listed = (
		service.permissions()
		.list(
			fileId=file_id,
			fields="permissions(id,type,role,emailAddress,permissionDetails(inherited,inheritedFrom))",
			supportsAllDrives=True,
		)
		.execute()
	)
	direct = {}
	for perm in listed.get("permissions", []):
		if perm.get("type") != "user" or not perm.get("emailAddress"):
			continue
		if _inherited_only(perm):
			continue
		direct[perm["emailAddress"].lower()] = perm
	return direct


def _inherited_only(perm: dict) -> bool:
	"""True when every grant behind this permission is inherited, none direct."""
	details = perm.get("permissionDetails") or []
	return bool(details) and all(d.get("inherited") for d in details)


# Roles that own or organize a file (on a Shared Drive the drive itself); Drive refuses to delete them.
STRUCTURAL_ROLES = ("owner", "organizer", "fileOrganizer")


def revoke_permissions(
	file_id: str,
	scope: str = "all",
	match: str = None,
	service=None,
	email_address: str = None,
) -> dict:
	"""Remove sharing grants from a file, the inverse of set_permissions.

	scope is all, domain or user, narrowed by match; email_address names one user. Structural and inherited
	grants and failed deletions land in skipped, so a partial withdrawal is reported in full.
	"""
	service = service or _get_service()
	listed = (
		service.permissions()
		.list(
			fileId=file_id,
			fields="permissions(id,type,role,emailAddress,domain,permissionDetails(inherited,inheritedFrom))",
			supportsAllDrives=True,
		)
		.execute()
	)

	if email_address:
		scope, match = "user", email_address

	removed = []
	skipped = []
	for perm in listed.get("permissions", []):
		if email_address and (
			perm.get("type") != "user" or (perm.get("emailAddress") or "").lower() != email_address.lower()
		):
			continue
		if perm.get("role") in STRUCTURAL_ROLES:
			skipped.append(dict(perm, reason="structural role"))
			continue
		if _inherited_only(perm):
			skipped.append(dict(perm, reason="inherited from a parent folder"))
			continue
		if scope in ("domain", "user") and perm.get("type") != scope:
			continue
		if match:
			target = perm.get("domain") if perm.get("type") == "domain" else perm.get("emailAddress")
			if (target or "").lower() != match.lower():
				continue

		try:
			service.permissions().delete(
				fileId=file_id, permissionId=perm["id"], supportsAllDrives=True
			).execute()
			removed.append(perm)
		except Exception as e:
			skipped.append(dict(perm, reason=str(e)))

	return {"removed": removed, "skipped": skipped}


def list_files(folder_id: str, page_size: int = 20, service=None) -> list:
	"""List non-trashed files directly inside a Drive folder."""
	service = service or _get_service()
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


def download_file_text(file_id: str, mime_type: str = None, service=None) -> str:
	"""Fetch a file's text: Drive export for native Docs and Slides, python-pptx or python-docx for uploads, else UTF-8.

	Pass mime_type when the caller already has it to save a round trip.
	"""
	service = service or _get_service()
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

	# Some editors report non-standard OOXML mimetypes such as application/wps-office.docx.
	mt = (mime_type or "").lower()
	is_pptx = mt == _PPTX_MIME or mt.endswith("pptx") or "presentationml" in mt
	is_docx = mt == _DOCX_MIME or mt.endswith("docx") or "wordprocessingml" in mt

	# OOXML files are ZIP containers; sniff the parts when the mimetype says nothing.
	if not (is_pptx or is_docx) and raw[:2] == b"PK":
		head = raw[:4000]
		if b"ppt/" in head:
			is_pptx = True
		elif b"word/" in head:
			is_docx = True

	if is_pptx:
		return _extract_pptx_text(raw)
	if is_docx:
		return _extract_docx_text(raw)

	return raw.decode("utf-8", errors="ignore")
