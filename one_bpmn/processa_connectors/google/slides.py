# Copyright (c) 2026, one-fm and contributors
"""Google Slides client (Slides API v1) for the google_slides connector; every call is retried on 429 and 5xx."""

from one_bpmn.processa_connectors.google import common as gc
from one_bpmn.processa_connectors.retry import call_with_retry


def _svc(connector_id="google_slides"):
	return gc.get_service("slides", "v1", scopes=[gc.SLIDES_SCOPE, gc.DRIVE_SCOPE], connector_id=connector_id)


def _run(request):
	return call_with_retry(request.execute)


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
	"""presentations.get and a walk, returning the plain text across all slides."""
	return _extract_text(get_presentation(presentation_id))


# Fill the ONE-FM Guideline deck by geometry (EMU, a 10 x 5.62 inch slide), which a fill does not change.

_EMU_PER_INCH = 914400
_TOC_ANCHOR = "table of contents"

# Only a content page carries a text box spanning nearly the full slide.
_BODY_MIN_WIDTH_IN = 8.0
# The header band holds the guideline name on top and the page title beneath it.
_HEADER_BAND_MAX_Y_IN = 1.5
# The Do's and Don'ts panels are the two tall rounded rectangles; their captions stay put.
_PANEL_MIN_HEIGHT_IN = 2.5


def batch_update(presentation_id: str, requests: list) -> dict:
	if not requests:
		return {}
	return _run(
		_svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests})
	)


def _text_of(element: dict) -> str:
	shape = element.get("shape") or {}
	return "".join(
		(te.get("textRun") or {}).get("content", "")
		for te in ((shape.get("text") or {}).get("textElements") or [])
	).strip()


def _box(element: dict) -> tuple:
	"""(x, y, w, h) of a page element in inches, scale applied."""
	tr = element.get("transform") or {}
	size = element.get("size") or {}
	w = (size.get("width") or {}).get("magnitude", 0) * tr.get("scaleX", 1)
	h = (size.get("height") or {}).get("magnitude", 0) * tr.get("scaleY", 1)
	return (
		tr.get("translateX", 0) / _EMU_PER_INCH,
		tr.get("translateY", 0) / _EMU_PER_INCH,
		w / _EMU_PER_INCH,
		h / _EMU_PER_INCH,
	)


def _shapes(slide: dict) -> list:
	return [pe for pe in (slide.get("pageElements") or []) if "shape" in pe]


def _shape_type(element: dict) -> str:
	return (element.get("shape") or {}).get("shapeType") or ""


def _is_content_page(slide: dict) -> bool:
	"""A content page is the one carrying a full-width body text box."""
	return any(_shape_type(pe) == "TEXT_BOX" and _box(pe)[2] >= _BODY_MIN_WIDTH_IN for pe in _shapes(slide))


def _is_dos_donts_page(slide: dict) -> bool:
	"""Two tall panels side by side, and no full-width body box."""
	panels = [
		pe
		for pe in _shapes(slide)
		if _shape_type(pe) == "ROUND_RECTANGLE" and _box(pe)[3] >= _PANEL_MIN_HEIGHT_IN
	]
	return len(panels) >= 2 and not _is_content_page(slide)


def _content_slots(slide: dict) -> dict:
	"""The three writable slots on a content page, by geometry.

	The name and title boxes are the same size, so vertical position tells them apart.
	"""
	body = max(
		(pe for pe in _shapes(slide) if _shape_type(pe) == "TEXT_BOX" and _box(pe)[2] >= _BODY_MIN_WIDTH_IN),
		key=lambda pe: _box(pe)[2],
		default=None,
	)
	header = sorted(
		(
			pe
			for pe in _shapes(slide)
			if _shape_type(pe) == "ROUND_RECTANGLE" and _box(pe)[1] < _HEADER_BAND_MAX_Y_IN
		),
		key=lambda pe: _box(pe)[1],
	)
	return {
		"name": header[0]["objectId"] if header else None,
		"title": header[1]["objectId"] if len(header) > 1 else None,
		"body": body["objectId"] if body else None,
	}


def _dos_donts_slots(slide: dict) -> dict:
	"""Left panel is Do's, right panel is Don'ts, ordered by x."""
	panels = sorted(
		(
			pe
			for pe in _shapes(slide)
			if _shape_type(pe) == "ROUND_RECTANGLE" and _box(pe)[3] >= _PANEL_MIN_HEIGHT_IN
		),
		key=lambda pe: _box(pe)[0],
	)
	header = sorted(
		(
			pe
			for pe in _shapes(slide)
			if _shape_type(pe) == "ROUND_RECTANGLE" and _box(pe)[1] < _HEADER_BAND_MAX_Y_IN
		),
		key=lambda pe: _box(pe)[1],
	)
	return {
		"name": header[0]["objectId"] if header else None,
		"dos": panels[0]["objectId"] if panels else None,
		"donts": panels[1]["objectId"] if len(panels) > 1 else None,
	}


def _toc_slot(slide: dict):
	for pe in _shapes(slide):
		if _TOC_ANCHOR in _text_of(pe).lower():
			return pe["objectId"]
	return None


def _rewrite(element_text: str, object_id: str, text: str) -> list:
	"""Clear a shape, when it has text, then write it, so a re-fill replaces the previous revision."""
	requests = []
	if element_text:
		requests.append({"deleteText": {"objectId": object_id, "textRange": {"type": "ALL"}}})
	if text:
		requests.append({"insertText": {"objectId": object_id, "insertionIndex": 0, "text": text}})
	return requests


def fill_branded_deck(presentation_id: str, content: dict) -> dict:
	"""Fill a copy of the ONE-FM Guideline deck in place from content: guideline_name, pages, dos and donts.

	The content page is duplicated once per page, surplus pages go, the table of contents is rebuilt from the titles,
	and every target not found comes back in unmatched.
	"""
	report = {
		"presentationId": presentation_id,
		"filled": {},
		"unmatched": [],
		"pages_added": 0,
		"pages_removed": 0,
	}
	content = content or {}
	name = str(content.get("guideline_name") or "").strip()
	pages = [p for p in (content.get("pages") or []) if p]
	dos = [str(d).strip() for d in (content.get("dos") or []) if str(d or "").strip()]
	donts = [str(d).strip() for d in (content.get("donts") or []) if str(d or "").strip()]

	if not pages:
		report["unmatched"].append("pages:nothing to write")
		return report

	pres = get_presentation(presentation_id)
	slides = pres.get("slides") or []
	content_slides = [s for s in slides if _is_content_page(s)]
	dos_slide = next((s for s in slides if _is_dos_donts_page(s)), None)

	if not content_slides:
		report["unmatched"].append("pages:no content page in this deck")
		return report

	# Pass one sizes the deck; duplicating a slide re-issues its object ids, so the deck is re-read before writing.
	shortfall = len(pages) - len(content_slides)
	if shortfall > 0:
		template_id = content_slides[-1]["objectId"]
		batch_update(
			presentation_id,
			[{"duplicateObject": {"objectId": template_id}} for _ in range(shortfall)],
		)
		report["pages_added"] = shortfall
	elif shortfall < 0:
		batch_update(
			presentation_id,
			[{"deleteObject": {"objectId": s["objectId"]}} for s in content_slides[len(pages) :]],
		)
		report["pages_removed"] = -shortfall

	if shortfall:
		pres = get_presentation(presentation_id)
		slides = pres.get("slides") or []
		content_slides = [s for s in slides if _is_content_page(s)]
		dos_slide = next((s for s in slides if _is_dos_donts_page(s)), None)
		# Content pages sit after the cover; Do's & Don'ts closes the deck.
		ordering = [
			{
				"updateSlidesPosition": {
					"slideObjectIds": [s["objectId"] for s in content_slides],
					"insertionIndex": 1,
				}
			}
		]
		if dos_slide:
			ordering.append(
				{
					"updateSlidesPosition": {
						"slideObjectIds": [dos_slide["objectId"]],
						"insertionIndex": len(slides) - 1,
					}
				}
			)
		batch_update(presentation_id, ordering)
		pres = get_presentation(presentation_id)
		slides = pres.get("slides") or []
		content_slides = [s for s in slides if _is_content_page(s)]
		dos_slide = next((s for s in slides if _is_dos_donts_page(s)), None)

	# Pass two clears and writes every target in one batch.
	requests = []
	by_id = {pe["objectId"]: pe for s in slides for pe in (s.get("pageElements") or [])}

	def write(object_id, text, label):
		if not object_id:
			report["unmatched"].append(label)
			return
		requests.extend(_rewrite(_text_of(by_id.get(object_id, {})), object_id, text))
		report["filled"][label] = len(text)

	for index, (slide, page) in enumerate(zip(content_slides, pages), start=1):
		slots = _content_slots(slide)
		write(slots["title"], str(page.get("title") or "").strip(), f"page{index}.title")
		write(slots["body"], str(page.get("body") or "").strip(), f"page{index}.body")
		if name:
			write(slots["name"], name, f"page{index}.name")

	if dos_slide:
		slots = _dos_donts_slots(dos_slide)
		write(slots["dos"], "\n".join(dos), "dos")
		write(slots["donts"], "\n".join(donts), "donts")
		if name:
			write(slots["name"], name, "dosdonts.name")
	elif dos or donts:
		report["unmatched"].append("dos/donts:no Do's & Don'ts page in this deck")

	# The cover: guideline name, and a table of contents rebuilt from the pages.
	cover = next((s for s in slides if not _is_content_page(s) and not _is_dos_donts_page(s)), None)
	if cover:
		toc_id = _toc_slot(cover)
		if toc_id:
			lines = ["Table of Contents:"]
			lines += [str(p.get("title") or "").strip() for p in pages]
			if dos_slide:
				lines.append("Do’s & Don'ts")
			write(toc_id, "\n".join(lines), "toc")
		else:
			report["unmatched"].append("toc:not found on the cover")
		if name:
			titled = [
				pe
				for pe in _shapes(cover)
				if _shape_type(pe) == "ROUND_RECTANGLE" and pe["objectId"] != toc_id
			]
			hero = max(titled, key=lambda pe: _box(pe)[2], default=None)
			write(hero["objectId"] if hero else None, name, "cover.name")
	else:
		report["unmatched"].append("cover:not found")

	batch_update(presentation_id, requests)
	return report
