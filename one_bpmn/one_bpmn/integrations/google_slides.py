# Copyright (c) 2026, one-fm and contributors
# Google Slides integration (Slides API v1), used by the google_slides connector.
#
# create_presentation goes through the DRIVE API (files.create with the
# presentation mimeType + a parent folder) rather than presentations.create, for
# the same reason google_sheets and google_docs do: presentations.create cannot
# target a folder, so the deck lands in the service account's My Drive — which
# has zero quota — and fails with storageQuotaExceeded. Structural edits then use
# the Slides API on that id.

from one_bpmn.one_bpmn.integrations import google_common as gc

SLIDES_MIME = "application/vnd.google-apps.presentation"


def _svc(connector_id="google_slides"):
    return gc.get_service("slides", "v1", scopes=[gc.SLIDES_SCOPE, gc.DRIVE_SCOPE], connector_id=connector_id)


def _drive(connector_id="google_slides"):
    return gc.get_service("drive", "v3", scopes=[gc.DRIVE_SCOPE], connector_id=connector_id)


def _run(request):
    return gc.call_with_retry(request.execute)


def batch_update(presentation_id: str, requests: list) -> dict:
    return _run(_svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}))


def get_presentation(presentation_id: str) -> dict:
    return _run(_svc().presentations().get(presentationId=presentation_id))


def _extract_text(pres: dict) -> str:
    out = []
    for i, slide in enumerate(pres.get("slides", []) or [], start=1):
        lines = [f"## Slide {i}"]
        for pe in slide.get("pageElements", []) or []:
            text = (pe.get("shape") or {}).get("text")
            if not text:
                continue
            for te in text.get("textElements", []) or []:
                tr = te.get("textRun")
                if tr and tr.get("content") and tr["content"].strip():
                    lines.append(tr["content"].strip())
        if len(lines) > 1:
            out.append("\n".join(lines))
    return "\n\n".join(out)


def get_text(presentation_id: str) -> str:
    """presentations.get + walk → plain text across all slides."""
    return _extract_text(get_presentation(presentation_id))
