# Copyright (c) 2026, one-fm and contributors
# Google Drive connector handlers.
#
# Thin wrappers over the existing, battle-tested integrations/google_drive.py
# functions. Each maps a real Drive v3 API method to a connector operation.
# params arrive resolved (Jinja-rendered, Drive ids normalized) from
# dispatch_connector; the returned dict lands in task.data[resultVariable].

import json

from one_bpmn.one_bpmn.connectors.registry import connector
from one_bpmn.one_bpmn.integrations import google_drive as gd


def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


@connector("google_drive", "downloadText")
def download_text(params, ctx):
    """files.export / get_media → plain text of a Doc/Slides/pptx/docx/txt."""
    return {"text": gd.download_file_text(params["file"])}


@connector("google_drive", "createFile")
def create_file(params, ctx):
    """files.create — upload content, optionally converting to a native Google type.

    The destination folder is given directly on the connector (``folder``).
    """
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


@connector("google_drive", "updateFileContent")
def update_file_content(params, ctx):
    """files.update — replace an existing file's content."""
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


@connector("google_drive", "setPermissions")
def set_permissions(params, ctx):
    """permissions.create — share a file.

    Either give a ready ``grants`` array (JSON), or a single grant via
    type/role/emailAddress/domain (the API's own enums).
    """
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


@connector("google_drive", "listFiles")
def list_files(params, ctx):
    """files.list — non-trashed files directly inside a folder."""
    files = gd.list_files(params["folder"], page_size=int(params.get("pageSize") or 20))
    return {"files": files, "count": len(files)}


@connector("google_drive", "deleteFile")
def delete_file(params, ctx):
    """files.delete / files.update(trashed) — trash (default) or permanently delete."""
    gd.delete_file(params["file"], permanent=_truthy(params.get("permanent")))
    return {"deleted": params["file"], "permanent": _truthy(params.get("permanent"))}
