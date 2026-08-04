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


def _svc(connector_id="google_docs"):
    return gc.get_service("docs", "v1", scopes=[gc.DOCS_SCOPE, gc.DRIVE_SCOPE], connector_id=connector_id)


def _run(request):
    return gc.call_with_retry(request.execute)


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


# ── The ONE-FM controlled-document templates ────────────────────────────────
# Filling the Policy / SOP / Manual templates without editing them.
#
# The templates were provided as finished, branded documents — bilingual EN/AR
# tables, the ONE/ﻭﻥ logos as positioned objects, an approval matrix — and they
# cannot be modified, so they carry no {{placeholders}} and never will. The fill
# has to work with what is already in them.
#
# Why this is not a find-and-replace:
#
#   * The body is a NUMBERED BILINGUAL TABLE, not a text block. The template
#     ships one example row; a policy with twelve clauses needs twelve rows, and
#     the numbering columns do not auto-fill, so each row's number is written in
#     both Latin and Arabic-Indic digits.
#   * Section content belongs in EMPTY cells under labels ("Purpose:" above a
#     blank). There is no text there to replace — the text has to be inserted at
#     a computed document index.
#   * On an Update the document has already been filled once, so the instruction
#     text that would identify the targets is gone. Targets are therefore found
#     STRUCTURALLY — by the labels and numbering that survive a fill — and each
#     one is cleared before it is rewritten. That is what makes filling
#     repeatable, which is what lets a revision keep the same Drive file, which
#     is what the document versioning depends on.
#
# Nothing here hardcodes a template's wording. The three word their instructions
# differently ("the Policy", "the Process / SOP", "the Manual" — with a double
# space in all three), so a fourth template works without a code change.

import re

_APPROVAL_ANCHOR = re.compile(r"development\s*&\s*approval\s+authority", re.I)
_ARABIC = re.compile(r"[؀-ۿ]")


def _arabic_indic(number: int) -> str:
	"""1 -> '١'. Every row is numbered in both scripts."""
	return "".join(chr(0x0660 + int(digit)) for digit in str(number))


def _is_latin_number(text: str) -> bool:
	# NOT str.isdigit(): that is also true of "١", which is how the Arabic
	# numbering column first came to be mistaken for the Latin one and overwrite
	# it — inserted rows numbered themselves in the wrong column.
	return bool(text) and text.isascii() and text.isdigit()


def _is_arabic_number(text: str) -> bool:
	return bool(text) and all(0x0660 <= ord(char) <= 0x0669 for char in text)


def _looks_arabic(text: str) -> bool:
	return bool(_ARABIC.search(text or ""))


def _cell_text(cell) -> str:
	out = []
	for element in cell.get("content", []) or []:
		paragraph = element.get("paragraph")
		if not paragraph:
			continue
		for run in paragraph.get("elements", []) or []:
			out.append((run.get("textRun") or {}).get("content", ""))
	return "".join(out).strip()


def _cell_paragraphs(cell):
	return [el for el in cell.get("content", []) or [] if el.get("paragraph")]


def _cell_insert_index(cell):
	"""Where text goes inside a cell — its first paragraph's start."""
	paragraphs = _cell_paragraphs(cell)
	return paragraphs[0].get("startIndex") if paragraphs else None


def _cell_text_range(cell):
	"""The span of a cell's existing text, or None if it is empty.

	Stops one short of the last paragraph's end: that final character is the
	cell's paragraph mark, and Docs rejects a delete that would remove it.
	"""
	paragraphs = _cell_paragraphs(cell)
	if not paragraphs:
		return None
	start = paragraphs[0].get("startIndex")
	end = paragraphs[-1].get("endIndex")
	if start is None or end is None or end - 1 <= start:
		return None
	return start, end - 1


def _iter_tables(document):
	"""Every table in the document, as (segment_id, element).

	Walks the page HEADERS and FOOTERS as well as the body, and recurses into
	tables nested inside table cells. Both matter, and each cost a bug: the
	Policy title also lives in a 2x1 table nested inside the running header —
	the copy that repeats on every printed page — so a fill that only walked
	the body left "Add  the title of the Policy" across the whole document
	while the body title looked correct.

	The segment id travels with the element because header and footer content
	has its own index space; an edit there is rejected, or lands in the wrong
	place, unless the request names its segment.
	"""
	def walk(content, segment_id):
		for element in content or []:
			if not element.get("table"):
				continue
			yield segment_id, element
			for row in element["table"].get("tableRows", []) or []:
				for cell in row.get("tableCells", []) or []:
					yield from walk(cell.get("content"), segment_id)

	yield from walk(document.get("body", {}).get("content"), "")
	for section in ("headers", "footers"):
		for segment_id, segment in (document.get(section) or {}).items():
			yield from walk(segment.get("content"), segment_id)


def _rows(element):
	return element["table"].get("tableRows", []) or []


def _cells(row):
	return row.get("tableCells", []) or []


def _find_title_slots(document):
	"""Every bilingual title slot, as (segment_id, english_cell, arabic_cell).

	A title slot is a table of exactly TWO cells holding an English/Arabic pair.
	That covers both shapes the templates use — the body's 1x2 pair and the
	header's nested 2x1 pair — and excludes everything else: the section tables
	have four cells, the approval matrix has twenty-four, the footer's page
	marker has three. Which cell is which is decided by script, so it keeps
	working on an Update when the cells hold a real title instead of the
	template's instruction text.

	It returns a LIST because there is more than one. The body title and the
	running-header title are the same title, and filling only the first is what
	left the header reading "Add  the title of the Policy" on every page.
	"""
	slots = []
	for segment_id, element in _iter_tables(document):
		cells = [cell for row in _rows(element) for cell in _cells(row)]
		if len(cells) != 2:
			continue
		texts = [_cell_text(cell) for cell in cells]
		if not any(texts):
			continue
		arabic = [index for index, text in enumerate(texts) if _looks_arabic(text)]
		if len(arabic) != 1:
			continue
		english_index = 1 - arabic[0]
		slots.append((segment_id, cells[english_index], cells[arabic[0]]))
	return slots


def _find_section_cell(document, label):
	"""The (segment_id, cell) that belongs to ``label`` — "Purpose:" and the like.

	The label sits in one row and its content goes in the row below, in the same
	column; a label in the last row falls back to the next column along. Matching
	ignores case and a trailing colon, because the templates are inconsistent
	about both. Emptiness is deliberately NOT part of the test: on an Update the
	cell already holds the previous revision's text.
	"""
	wanted = label.strip().rstrip(":").casefold()
	for segment_id, element in _iter_tables(document):
		rows = _rows(element)
		for row_index, row in enumerate(rows):
			cells = _cells(row)
			for column, cell in enumerate(cells):
				if _cell_text(cell).rstrip(":").casefold() != wanted:
					continue
				if row_index + 1 < len(rows):
					below = _cells(rows[row_index + 1])
					if column < len(below):
						return segment_id, below[column]
				if column + 1 < len(cells):
					return segment_id, cells[column + 1]
	return None


def _find_item_table(document):
	"""The numbered clause/step table, and which column holds what.

	Anchored on the numbering, which is the one thing that is present both in the
	pristine template and after a fill: the first row holding a plain "1". The
	columns are then read off that row — the Latin number, the Arabic-Indic
	number, and of the two remaining the Arabic-script one is the AR column.
	"""
	for segment_id, element in _iter_tables(document):
		rows = _rows(element)
		for row_index, row in enumerate(rows):
			texts = [_cell_text(cell) for cell in _cells(row)]
			if not any(_is_latin_number(text) and text == "1" for text in texts):
				continue
			layout = {
				"segment": segment_id,
				"table": element,
				"start_row": row_index,
				"rows": len(rows),
				"columns": len(texts),
			}
			rest = []
			for column, text in enumerate(texts):
				if _is_arabic_number(text):
					layout["num_ar"] = column
				elif _is_latin_number(text):
					layout["num"] = column
				else:
					rest.append((column, text))
			for column, text in rest:
				layout["ar" if _looks_arabic(text) else "en"] = column
			return layout
	return None


def _find_intro_cells(layout):
	"""The Manual's opening-statement cells, if this template has them.

	Manual has no "Purpose:" table — its opening statement is instruction text in
	the item table's first row ("EXPLAIN WHAT THIS MANUAL IS ABOUT"). Policy and
	SOP use that same row for a heading instead ("Policy:", "Procedure:"), and
	the colon is what tells them apart: a heading ends in one, a statement does
	not. Without this the purpose the model wrote would have nowhere to go on a
	Manual and would be dropped silently.
	"""
	if not layout or layout["start_row"] < 1:
		return None, None
	first = _cells(_rows(layout["table"])[0])
	texts = [_cell_text(cell) for cell in first]
	if not any(texts) or any(text.endswith(":") for text in texts):
		return None, None
	english = arabic = None
	for cell, text in zip(first, texts):
		if not text:
			continue
		if _looks_arabic(text):
			arabic = cell
		else:
			english = cell
	return english, arabic


def fill_branded_template(document_id: str, content: dict) -> dict:
	"""Fill a copy of a ONE-FM template in place, keeping everything it already is.

	``content`` is the document expressed as fields rather than prose::

	    {
	      "title": "Workflow States Definition Policy",
	      "title_ar": "سياسة تحديد حالات سير العمل",
	      "intro": "…",                        # Manual only
	      "sections": {"Purpose": "…", "الغرض": "…"},
	      "items": [{"en": "Clause one.", "ar": "البند الأول."}, …],
	    }

	Two write calls: one to make the item table the right length, one to clear and
	rewrite every target. Batching the writes matters — a branded policy published
	with "Write your Policy here" still standing in clause 1, or holding half of
	one revision and half of the next, is the outcome this exists to prevent.
	Which is also why every target that could not be found comes back in
	``unmatched`` rather than being quietly skipped.

	Re-running it replaces the content instead of appending to it, so an Update
	revises the same Drive file rather than needing a new one.
	"""
	report = {"documentId": document_id, "filled": {}, "unmatched": [],
	          "rows_added": 0, "rows_removed": 0}
	items = [item for item in (content or {}).get("items") or [] if item]
	sections = {
		label: str(text) for label, text in ((content or {}).get("sections") or {}).items()
		if str(text or "").strip()
	}

	document = get_document(document_id)
	layout = _find_item_table(document)
	if items and not layout:
		report["unmatched"].append("items:no numbered table in this template")

	# Pass one — make the table the right length. Row edits move every index that
	# follows them, so they cannot share a batch with writes whose indices were
	# computed beforehand.
	if layout and items:
		table_start = layout["table"]["startIndex"]
		table_location = {"index": table_start, "segmentId": layout.get("segment") or ""}
		available = layout["rows"] - layout["start_row"]
		shortfall = len(items) - available
		requests = []
		if shortfall > 0:
			requests = [
				{"insertTableRow": {
					"tableCellLocation": {
						"tableStartLocation": table_location,
						"rowIndex": layout["rows"] - 1 + offset,
						"columnIndex": 0,
					},
					"insertBelow": True,
				}}
				for offset in range(shortfall)
			]
			report["rows_added"] = shortfall
		elif shortfall < 0:
			# Bottom-up: deleting a row renumbers everything below it.
			requests = [
				{"deleteTableRow": {
					"tableCellLocation": {
						"tableStartLocation": table_location,
						"rowIndex": row_index,
						"columnIndex": 0,
					}
				}}
				for row_index in range(layout["rows"] - 1,
				                       layout["start_row"] + len(items) - 1, -1)
			]
			report["rows_removed"] = -shortfall
		if requests:
			batch_update(document_id, requests)
			document = get_document(document_id)
			layout = _find_item_table(document)

	# Pass two — collect every (cell, value) pair, then clear and write each.
	targets = []

	# Every title slot, not just the first: the body carries one and the running
	# page header carries another, and they are the same title.
	slots = _find_title_slots(document)
	title = str((content or {}).get("title") or "").strip()
	title_ar = str((content or {}).get("title_ar") or "").strip()
	if title or title_ar:
		if not slots:
			report["unmatched"].append("title:no title slot in this template")
		for segment_id, english_cell, arabic_cell in slots:
			if title:
				targets.append((segment_id, english_cell, title))
			if title_ar:
				targets.append((segment_id, arabic_cell, title_ar))
		report["filled"]["title_slots"] = len(slots)

	intro_en, intro_ar = _find_intro_cells(layout)
	for key, cell in (("intro", intro_en), ("intro_ar", intro_ar)):
		value = str((content or {}).get(key) or "").strip()
		if not value:
			continue
		if cell is None:
			report["unmatched"].append(f"{key}:not in this template")
		else:
			targets.append((layout.get("segment") or "", cell, value))
			report["filled"][key] = 1

	for label, text in sections.items():
		found = _find_section_cell(document, label)
		if found is None:
			report["unmatched"].append(f"section:{label}")
		else:
			targets.append((found[0], found[1], text))
	report["filled"]["sections"] = len(sections) - len(
		[u for u in report["unmatched"] if u.startswith("section:")]
	)

	if layout and items:
		rows = _rows(layout["table"])
		for offset, item in enumerate(items):
			row_index = layout["start_row"] + offset
			if row_index >= len(rows):
				report["unmatched"].append(f"item:{offset + 1}:no row")
				continue
			cells = _cells(rows[row_index])
			for key, value in (
				("en", str(item.get("en") or "")),
				("ar", str(item.get("ar") or "")),
				("num", str(offset + 1)),
				("num_ar", _arabic_indic(offset + 1)),
			):
				column = layout.get(key)
				if column is None or column >= len(cells) or not value:
					continue
				targets.append((layout.get("segment") or "", cells[column], value))
		report["filled"]["items"] = len(items)

	# Descending, so that clearing and rewriting one cell leaves every index
	# below it untouched and the whole document can go in a single batch.
	edits = []
	for segment_id, cell, value in targets:
		span = _cell_text_range(cell)
		index = span[0] if span else _cell_insert_index(cell)
		if index is None:
			report["unmatched"].append("cell:no insertion point")
			continue
		edits.append((index, span[1] if span else None, value, segment_id))

	# Descending by index. Each segment has its own index space, and sorting the
	# whole list descending keeps it descending WITHIN every segment, which is
	# all that is needed for earlier edits to leave later indices valid.
	requests = []
	for index, end, value, segment_id in sorted(edits, key=lambda edit: edit[0], reverse=True):
		if end is not None:
			requests.append({"deleteContentRange": {
				"range": {"startIndex": index, "endIndex": end, "segmentId": segment_id}
			}})
		requests.append({"insertText": {
			"location": {"index": index, "segmentId": segment_id}, "text": value
		}})

	if requests:
		batch_update(document_id, requests)
	return report
