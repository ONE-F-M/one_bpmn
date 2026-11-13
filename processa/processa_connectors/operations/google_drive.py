# Copyright (c) 2026, one-fm and contributors
"""Google Drive connector handlers over google/drive.py; params arrive rendered and with Drive ids normalized."""

import json

from processa.processa_connectors.google import common as gc
from processa.processa_connectors.google import drive as gd


def _truthy(v):
	if isinstance(v, bool):
		return v
	return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def list_file_choices(folder=None, **_ignored):
	"""Choices From path listing the files in the folder chosen in a sibling folder field."""
	if not folder:
		return []
	files = gd.list_files(gc.normalize_drive_id(folder))
	return [{"label": f.get("name") or f.get("id"), "value": f.get("id")} for f in files]


def download_text(params, ctx):
	"""files.export or get_media, returning the plain text of a Doc, Slides, pptx, docx or txt file."""
	return {"text": gd.download_file_text(params["file"])}


def create_file(params, ctx):
	"""files.create: upload content into the connector's folder, optionally converting to a native Google type."""
	folder_id = params.get("folder")
	if not folder_id:
		raise gd.GoogleDriveConfigError("createFile requires a Folder (Drive folder link or id).")
	created = gd.create_file(
		folder_id=folder_id,
		filename=params.get("filename") or "Untitled Document",
		content=params.get("content") or "",
		target_mime_type=params.get("targetMimeType") or "application/vnd.google-apps.document",
		source_mime_type=params.get("sourceMimeType") or "text/markdown",
	)
	return {
		"id": created.get("id"),
		"name": created.get("name"),
		"webViewLink": created.get("webViewLink"),
	}


def update_file_content(params, ctx):
	"""files.update: replace an existing file's content."""
	updated = gd.update_file_content(
		params["file"],
		params.get("content") or "",
		source_mime_type=params.get("sourceMimeType") or "text/markdown",
	)
	return {
		"id": updated.get("id"),
		"name": updated.get("name"),
		"webViewLink": updated.get("webViewLink"),
	}


def set_permissions(params, ctx):
	"""permissions.create: share a file with a grants JSON array or one grant from type, role, emailAddress and domain."""
	grants = params.get("grants")
	if isinstance(grants, str) and grants.strip():
		grants = json.loads(grants)
	if not grants:
		grant = {"type": params["type"], "role": params["role"]}
		if params.get("emailAddress"):
			grant["emailAddress"] = params["emailAddress"]
		if params.get("domain"):
			grant["domain"] = params["domain"]
		grants = [grant]
	results = gd.set_permissions(params["file"], grants)
	return {"granted": len(results)}


def revoke_permissions(params, ctx):
	"""permissions.list and permissions.delete: withdraw sharing without touching the content."""
	outcome = gd.revoke_permissions(
		params["file"],
		scope=(params.get("scope") or "all").strip(),
		match=(params.get("match") or "").strip() or None,
		email_address=(params.get("emailAddress") or "").strip() or None,
	)
	# skipped is reported because some Shared Drive grants cannot be removed on the item.
	return {
		"revoked": len(outcome["removed"]),
		"skipped": len(outcome["skipped"]),
		"grants": outcome["removed"],
		"skipped_grants": outcome["skipped"],
		"file": params["file"],
	}
