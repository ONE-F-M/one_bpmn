# Copyright (c) 2026, one-fm and contributors
# Google Drive connector handlers.
#
# Thin wrappers over the existing, battle-tested integrations/google_drive.py
# functions. Each maps a real Drive v3 API method to a connector operation.
# params arrive resolved (Jinja-rendered, Drive ids normalized) from
# dispatch_connector; the returned dict lands in task.data[resultVariable].

import json

from one_bpmn.one_bpmn.integrations import google_drive as gd


def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def list_file_choices(folder=None, **_ignored):
    """Dropdown choices for a field configured with this as its Choices From path.

    Point a field's ``choices_source_path`` here to let the modeler pick a file
    from the folder chosen in a sibling ``folder`` field, instead of pasting an
    id. Lives with the Drive connector rather than in connectors/api.py so the
    generic choices endpoint knows nothing about Google.
    """
    from one_bpmn.one_bpmn.integrations import google_common as gc

    if not folder:
        return []
    files = gd.list_files(gc.normalize_drive_id(folder))
    return [{"label": f.get("name") or f.get("id"), "value": f.get("id")} for f in files]


def download_text(params, ctx):
    """files.export / get_media → plain text of a Doc/Slides/pptx/docx/txt."""
    return {"text": gd.download_file_text(params["file"])}


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


def revoke_permissions(params, ctx):
    """permissions.list + permissions.delete — withdraw sharing without touching content.

    The counterpart to setPermissions. Used to take a document out of
    circulation: the file and its history stay exactly as they are, but the
    people who could open it no longer can.
    """
    outcome = gd.revoke_permissions(
        params["file"],
        scope=(params.get("scope") or "all").strip(),
        match=(params.get("match") or "").strip() or None,
    )
    # `skipped` is reported, not hidden: on a Shared Drive some grants cannot be
    # removed on the item at all, and a caller reading only a count would take
    # "revoked: 1" as "nobody can see it now".
    return {
        "revoked": len(outcome["removed"]),
        "skipped": len(outcome["skipped"]),
        "grants": outcome["removed"],
        "skipped_grants": outcome["skipped"],
        "file": params["file"],
    }
