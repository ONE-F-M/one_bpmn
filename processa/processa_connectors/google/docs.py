# Copyright (c) 2026, one-fm and contributors
"""Google Docs client (Docs API v1) for the google_docs connector; every call is retried on 429 and 5xx."""

import re

from processa.processa_connectors.google import common as gc
from processa.processa_connectors.retry import call_with_retry


def _svc(connector_id="google_docs"):
	return gc.get_service("docs", "v1", scopes=[gc.DOCS_SCOPE, gc.DRIVE_SCOPE], connector_id=connector_id)


def _run(request):
	return call_with_retry(request.execute)


def batch_update(document_id: str, requests: list) -> dict:
	"""documents.batchUpdate: apply a list of Docs API request objects."""
	return _run(_svc().documents().batchUpdate(documentId=document_id, body={"requests": requests}))


def get_document(document_id: str) -> dict:
	return _run(_svc().documents().get(documentId=document_id))


def insert_text(document_id: str, text: str, index: int = 1) -> dict:
	"""documents.batchUpdate insertText at a 1-based structural index."""
	batch_update(document_id, [{"insertText": {"location": {"index": int(index)}, "text": text or ""}}])
	return {"documentId": document_id}


def append_text(document_id: str, text: str) -> dict:
	"""Append to the end of the document body (before the trailing newline)."""
	content = get_document(document_id).get("body", {}).get("content", [])
	end_index = content[-1].get("endIndex", 2) if content else 2
	insert_text(document_id, text, index=max(1, end_index - 1))
	return {"documentId": document_id}


def fill_template(document_id: str, values: dict, match_case: bool = True) -> dict:
	"""Substitute every placeholder, such as {"{{title}}": "Leave Policy"}, in one atomic batchUpdate call.

	replaceAllText only matches text inside one formatting run, so a zero count in the result is the only sign
	that a placeholder was skipped; callers treat unfilled placeholders as a failure.
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
	"""documents.get and a structural walk, returning the plain text of the body."""
	return _extract_text(get_document(document_id))


# Fill the ONE-FM Policy, SOP and Manual templates, which carry no placeholders, by finding targets from their structure.

_APPROVAL_ANCHOR = re.compile(r"development\s*&\s*approval\s+authority", re.I)
_ARABIC = re.compile(r"[؀-ۿ]")


def _arabic_indic(number: int) -> str:
	"""1 -> '١'. Every row is numbered in both scripts."""
	return "".join(chr(0x0660 + int(digit)) for digit in str(number))


def _is_latin_number(text: str) -> bool:
	# Not str.isdigit(), which is also true of Arabic-Indic digits.
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
	"""Where text goes inside a cell: its first paragraph's start."""
	paragraphs = _cell_paragraphs(cell)
	return paragraphs[0].get("startIndex") if paragraphs else None


def _cell_text_range(cell):
	"""The span of a cell's existing text, or None if it is empty.

	Stops one short of the end: the last character is the cell's paragraph mark, which Docs refuses to delete.
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
	"""Every table in the document as (segment_id, element), headers, footers and nested tables included.

	Header and footer content has its own index space, so an edit there must name its segment.
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


def _is_merged(row):
	"""True for a row whose cells are merged across, like a screenshot row."""
	return any(int((cell.get("tableCellStyle") or {}).get("columnSpan") or 1) > 1 for cell in _cells(row))


def _find_title_slots(document):
	"""Every bilingual title slot as (segment_id, english_cell, arabic_cell): a table of exactly two cells.

	The body and the running header each carry the title, so all slots are returned; script decides which cell is which.
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
	"""The (segment_id, cell) under label, such as "Purpose:", or the next cell along when the label is in the last row.

	Case and a trailing colon are ignored; the cell may already hold the previous revision's text.
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
	"""The numbered clause or step table and which column holds what, anchored on the first row holding a plain "1".

	The Latin and Arabic-Indic number columns are read off that row; of the other two, the Arabic-script one is AR.
	"""
	for segment_id, element in _iter_tables(document):
		rows = _rows(element)
		for row_index, row in enumerate(rows):
			texts = [_cell_text(cell) for cell in _cells(row)]
			if not any(_is_latin_number(text) and text == "1" for text in texts):
				continue
			companions = 0
			while row_index + 1 + companions < len(rows) and _is_merged(rows[row_index + 1 + companions]):
				companions += 1
			layout = {
				"segment": segment_id,
				"table": element,
				"start_row": row_index,
				"rows": len(rows),
				"columns": len(texts),
				# A step row plus the merged rows the template puts under each step.
				"stride": 1 + companions,
				"footer": 0,
			}
			# With no merged rows under a step, merged rows at the end belong to no step.
			if not companions:
				while layout["footer"] < len(rows) - row_index - 1:
					if not _is_merged(rows[len(rows) - 1 - layout["footer"]]):
						break
					layout["footer"] += 1
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
	"""The Manual's opening-statement cells in the item table's first row, or (None, None).

	Policy and SOP use that row for a heading ending in a colon, which is what tells them apart.
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
	"""Fill a copy of a ONE-FM template in place from content: title, title_ar, intro, sections and items.

	One call sizes the item table and one rewrites every target; targets not found come back in unmatched.
	Re-running replaces the content, so an Update revises the same Drive file.
	"""
	report = {"documentId": document_id, "filled": {}, "unmatched": [], "rows_added": 0, "rows_removed": 0}
	items = [item for item in (content or {}).get("items") or [] if item]
	sections = {
		label: str(text)
		for label, text in ((content or {}).get("sections") or {}).items()
		if str(text or "").strip()
	}

	document = get_document(document_id)
	layout = _find_item_table(document)
	if items and not layout:
		report["unmatched"].append("items:no numbered table in this template")

	# Pass one sizes the table; row edits move later indices, so they cannot share a batch with the writes.
	if layout and items:
		stride, footer = layout["stride"], layout["footer"]
		table_location = {"index": layout["table"]["startIndex"], "segmentId": layout.get("segment") or ""}
		steps_end = layout["rows"] - footer
		wanted_end = layout["start_row"] + len(items) * stride
		shortfall = wanted_end - steps_end
		requests = []
		if shortfall > 0:
			requests = [
				{
					"insertTableRow": {
						"tableCellLocation": {
							"tableStartLocation": table_location,
							"rowIndex": steps_end - 1 + offset,
							"columnIndex": 0,
						},
						"insertBelow": True,
					}
				}
				for offset in range(shortfall)
			]
			report["rows_added"] = shortfall
		elif shortfall < 0:
			# Bottom-up: deleting a row renumbers everything below it.
			requests = [
				{
					"deleteTableRow": {
						"tableCellLocation": {
							"tableStartLocation": table_location,
							"rowIndex": row_index,
							"columnIndex": 0,
						}
					}
				}
				for row_index in range(steps_end - 1, wanted_end - 1, -1)
			]
			report["rows_removed"] = -shortfall
		if requests:
			batch_update(document_id, requests)
			document = get_document(document_id)
			layout = _find_item_table(document)

		if _reset_row_merges(document_id, layout, stride, table_location, wanted_end):
			document = get_document(document_id)
			layout = _find_item_table(document)
		layout["stride"], layout["footer"] = stride, footer

	# Pass two collects every (cell, value) pair, then clears and writes each.
	targets = []

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
			row_index = layout["start_row"] + offset * layout["stride"]
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

	edits = []
	for segment_id, cell, value in targets:
		span = _cell_text_range(cell)
		index = span[0] if span else _cell_insert_index(cell)
		if index is None:
			report["unmatched"].append("cell:no insertion point")
			continue
		edits.append((index, span[1] if span else None, value, segment_id))

	# Descending by index keeps each segment's later indices valid, so the whole document goes in one batch.
	requests = []
	for index, end, value, segment_id in sorted(edits, key=lambda edit: edit[0], reverse=True):
		if end is not None:
			requests.append(
				{
					"deleteContentRange": {
						"range": {"startIndex": index, "endIndex": end, "segmentId": segment_id}
					}
				}
			)
		requests.append(
			{"insertText": {"location": {"index": index, "segmentId": segment_id}, "text": value}}
		)

	if requests:
		batch_update(document_id, requests)
	return report


def _reset_row_merges(document_id, layout, stride, table_location, stop):
	"""Merge or unmerge item rows back to the template's step pattern. Returns True if it wrote."""
	# A new row copies the merge of the row above it, so reset every row to the template's pattern.
	requests = []
	for row_index, row in enumerate(
		_rows(layout["table"])[layout["start_row"] : stop], start=layout["start_row"]
	):
		should_merge = (row_index - layout["start_row"]) % stride != 0
		if should_merge == _is_merged(row):
			continue
		requests.append(
			{
				("mergeTableCells" if should_merge else "unmergeTableCells"): {
					"tableRange": {
						"tableCellLocation": {
							"tableStartLocation": table_location,
							"rowIndex": row_index,
							"columnIndex": 0,
						},
						"rowSpan": 1,
						"columnSpan": layout["columns"],
					}
				}
			}
		)
	if requests:
		batch_update(document_id, requests)
	return bool(requests)
