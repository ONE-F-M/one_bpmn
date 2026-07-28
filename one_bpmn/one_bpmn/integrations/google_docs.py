# Copyright (c) 2026, one-fm and contributors
# Google Docs integration (Docs API v1), used by the google_docs connector.
# Shares credentials/plumbing with google_common; all calls go through
# call_with_retry so transient 429/5xx are retried.

from one_bpmn.one_bpmn.integrations import google_common as gc


def _svc():
    return gc.get_service("docs", "v1", scopes=[gc.DOCS_SCOPE, gc.DRIVE_SCOPE])


def _run(request):
    return gc.call_with_retry(request.execute)


def create_document(title: str) -> dict:
    """documents.create — a new empty Google Doc."""
    doc = _run(_svc().documents().create(body={"title": title or "Untitled Document"}))
    return {"documentId": doc.get("documentId"), "title": doc.get("title")}


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
