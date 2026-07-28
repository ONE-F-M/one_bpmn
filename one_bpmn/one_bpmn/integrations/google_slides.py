# Copyright (c) 2026, one-fm and contributors
# Google Slides integration (Slides API v1), used by the google_slides connector.

from one_bpmn.one_bpmn.integrations import google_common as gc


def _svc():
    return gc.get_service("slides", "v1", scopes=[gc.SLIDES_SCOPE, gc.DRIVE_SCOPE])


def _run(request):
    return gc.call_with_retry(request.execute)


def create_presentation(title: str) -> dict:
    """presentations.create — a new empty deck."""
    p = _run(_svc().presentations().create(body={"title": title or "Untitled Presentation"}))
    return {"presentationId": p.get("presentationId"), "title": p.get("title")}


def batch_update(presentation_id: str, requests: list) -> dict:
    return _run(_svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}))


def get_presentation(presentation_id: str) -> dict:
    return _run(_svc().presentations().get(presentationId=presentation_id))


def replace_all_text(presentation_id: str, find: str, replace: str, match_case: bool = False) -> dict:
    """presentations.batchUpdate → replaceAllText (deck templating from placeholders)."""
    res = batch_update(presentation_id, [{
        "replaceAllText": {
            "containsText": {"text": find, "matchCase": bool(match_case)},
            "replaceText": replace or "",
        }
    }])
    changed = sum((r.get("replaceAllText", {}) or {}).get("occurrencesChanged", 0) or 0
                  for r in res.get("replies", []) or [])
    return {"presentationId": presentation_id, "occurrencesChanged": changed}


def create_slide(presentation_id: str, layout: str = None) -> dict:
    """presentations.batchUpdate → createSlide (optional predefined layout)."""
    req = {"createSlide": {}}
    if layout:
        req["createSlide"]["slideLayoutReference"] = {"predefinedLayout": layout}
    res = batch_update(presentation_id, [req])
    obj = next((((r.get("createSlide", {}) or {}).get("objectId")) for r in res.get("replies", []) or []
                if r.get("createSlide")), None)
    return {"presentationId": presentation_id, "slideObjectId": obj}


def duplicate_slide(presentation_id: str, object_id: str) -> dict:
    """presentations.batchUpdate → duplicateObject on a slide."""
    res = batch_update(presentation_id, [{"duplicateObject": {"objectId": object_id}}])
    dup = next((((r.get("duplicateObject", {}) or {}).get("objectId")) for r in res.get("replies", []) or []
                if r.get("duplicateObject")), None)
    return {"presentationId": presentation_id, "duplicatedObjectId": dup}


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
