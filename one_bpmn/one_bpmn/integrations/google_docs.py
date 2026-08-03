# Copyright (c) 2026, one-fm and contributors
# Google Docs integration (Docs API v1), used by the google_docs connector.
# Shares credentials/plumbing with google_common; all calls go through
# call_with_retry so transient 429/5xx are retried.
#
# create_document goes through the DRIVE API (files.create with the document
# mimeType + a parent folder) rather than documents.create, for the same reason
# google_sheets does: documents.create cannot target a folder, so the new file
# lands in the service account's My Drive — which has zero quota — and fails with
# storageQuotaExceeded. Creating it in a Shared Drive folder the service account
# belongs to is the only thing that works. Structural edits then use the Docs API
# on that id.

from one_bpmn.one_bpmn.integrations import google_common as gc

DOC_MIME = "application/vnd.google-apps.document"


def _svc():
    return gc.get_service("docs", "v1", scopes=[gc.DOCS_SCOPE, gc.DRIVE_SCOPE])


def _drive():
    return gc.get_service("drive", "v3", scopes=[gc.DRIVE_SCOPE])


def _run(request):
    return gc.call_with_retry(request.execute)


def create_document(title: str, folder: str) -> dict:
    """Create an empty Google Doc inside a Drive folder (Shared-Drive safe)."""
    if not folder:
        raise gc.GoogleConfigError(
            "createDocument requires a Folder — a service account has no My Drive "
            "quota, so the document must be created inside a Shared Drive folder."
        )
    body = {"name": title or "Untitled Document", "mimeType": DOC_MIME, "parents": [folder]}
    f = _run(_drive().files().create(body=body, fields="id,name,webViewLink", supportsAllDrives=True))
    return {"documentId": f.get("id"), "title": f.get("name"), "url": f.get("webViewLink")}


def batch_update(document_id: str, requests: list) -> dict:
    """documents.batchUpdate — apply a list of Docs API request objects."""
    return _run(_svc().documents().batchUpdate(documentId=document_id, body={"requests": requests}))


def get_document(document_id: str) -> dict:
    return _run(_svc().documents().get(documentId=document_id))


def insert_text(document_id: str, text: str, index: int = 1) -> dict:
    """documents.batchUpdate → insertText at a 1-based structural index."""
    batch_update(document_id, [{"insertText": {"location": {"index": int(index)}, "text": text or ""}}])
    return {"documentId": document_id}


def append_text(document_id: str, text: str) -> dict:
    """Append to the end of the document body (before the trailing newline)."""
    content = get_document(document_id).get("body", {}).get("content", [])
    end_index = content[-1].get("endIndex", 2) if content else 2
    insert_text(document_id, text, index=max(1, end_index - 1))
    return {"documentId": document_id}


def replace_all_text(document_id: str, find: str, replace: str, match_case: bool = False) -> dict:
    """documents.batchUpdate → replaceAllText (template placeholder fill)."""
    res = batch_update(document_id, [{
        "replaceAllText": {
            "containsText": {"text": find, "matchCase": bool(match_case)},
            "replaceText": replace or "",
        }
    }])
    changed = sum((r.get("replaceAllText", {}) or {}).get("occurrencesChanged", 0) or 0
                  for r in res.get("replies", []) or [])
    return {"documentId": document_id, "occurrencesChanged": changed}


def fill_template(document_id: str, values: dict, match_case: bool = True) -> dict:
	"""Substitute every placeholder in one ``batchUpdate`` call.

	``values`` maps placeholder text to replacement, e.g.
	``{"{{title}}": "Leave Policy", "{{owner}}": "HR"}``.

	One call rather than one per field, for two reasons: a template has ten-odd
	placeholders and ten round-trips is wasteful, and — more importantly —
	batchUpdate is atomic. Filling field by field can leave a document half
	populated if the fourth call fails, and a half-filled policy published to
	the domain is worse than one that failed outright.

	Returns a per-placeholder count of what was actually substituted. That
	detail matters: ``replaceAllText`` only matches text inside a single
	formatting run, so a placeholder someone part-bolded while editing the
	template is silently skipped. A zero in this result is the only signal that
	happened — callers should treat unfilled placeholders as a failure rather
	than shipping a document with ``{{owner}}`` still visible in it.
	"""
	pairs = [(str(k), "" if v is None else str(v)) for k, v in (values or {}).items() if str(k)]
	if not pairs:
		return {"documentId": document_id, "filled": {}, "unfilled": [], "total": 0}

	res = batch_update(
		document_id,
		[
			{
				"replaceAllText": {
					"containsText": {"text": find, "matchCase": bool(match_case)},
					"replaceText": replace,
				}
			}
			for find, replace in pairs
		],
	)

	replies = res.get("replies", []) or []
	filled = {}
	for i, (find, _) in enumerate(pairs):
		reply = replies[i] if i < len(replies) else {}
		filled[find] = (reply.get("replaceAllText", {}) or {}).get("occurrencesChanged", 0) or 0

	return {
		"documentId": document_id,
		"filled": filled,
		"unfilled": [k for k, n in filled.items() if not n],
		"total": sum(filled.values()),
	}


def _extract_text(doc: dict) -> str:
    out = []
    for el in doc.get("body", {}).get("content", []) or []:
        para = el.get("paragraph")
        if not para:
            continue
        for pe in para.get("elements", []) or []:
            tr = pe.get("textRun")
            if tr and tr.get("content"):
                out.append(tr["content"])
    return "".join(out)


def get_text(document_id: str) -> str:
    """documents.get + structural walk → plain text of the document body."""
    return _extract_text(get_document(document_id))
