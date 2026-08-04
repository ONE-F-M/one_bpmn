# -*- coding: utf-8 -*-
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Filling a branded template that has no placeholders and cannot be given any.

The ONE-FM Policy/SOP/Manual templates were provided as finished documents. They
carry no {{markers}}, and the people who own them cannot change them — so the
process had to. What makes that possible is that the templates already contain
targets: instruction text, empty cells under labels, and a numbered bilingual
table with one example row.

Every test here is a defect that actually shipped or was caught in review, not a
restatement of the implementation:

  * "١".isdigit() is True, so the Arabic numbering column was mistaken for the
    Latin one and overwrote it — inserted rows numbered themselves in the wrong
    column and left the right one blank.
  * The title also lives in a 2x1 table NESTED INSIDE THE RUNNING PAGE HEADER.
    A body-only walk left "Add  the title of the Policy" printed on every page
    of a published Policy while the body title looked perfectly correct. The API
    view hid this: documents.get returns the header, but a walker that does not
    recurse into nested tables never reaches it.
  * Header content has its own index space, so an edit there must name its
    segment or it lands in the wrong place.
  * An Update re-fills a document that is already full. Without clearing first,
    revision 2's text was appended to revision 1's.

Nothing here touches the network: batch_update and get_document are faked, and
the fake document is shaped like the real Policy template (verified against it —
see test_branded_templates.py for the operation-level tests).
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.integrations import google_docs as gdocs

DOC_ID = "_TestBrandedCopy"
HEADER_SEGMENT = "hdr.default"


# ── a fake document shaped like the real Policy template ─────────────────────

class _Builder:
	"""Builds Docs-API-shaped content with plausible, increasing indices."""

	def __init__(self):
		self.index = 1

	def cell(self, text):
		start = self.index
		self.index += max(len(text), 0) + 1
		return {
			"startIndex": start - 1,
			"endIndex": self.index,
			"content": [{
				"startIndex": start,
				"endIndex": self.index,
				"paragraph": {"elements": (
					[{"textRun": {"content": text}}] if text else [{"textRun": {"content": "\n"}}]
				)},
			}],
		}

	def table(self, rows, nested=None):
		start = self.index
		self.index += 1
		built = []
		for row in rows:
			built.append({"tableCells": [self.cell(text) for text in row]})
		element = {
			"startIndex": start,
			"endIndex": self.index,
			"table": {
				"rows": len(rows),
				"columns": len(rows[0]) if rows else 0,
				"tableRows": built,
			},
		}
		if nested is not None:
			row_index, column_index, inner = nested
			element["table"]["tableRows"][row_index]["tableCells"][column_index]["content"].append(inner)
		return element


def policy_document(title_en="Add  the title of the Policy",
                    title_ar="أضف عنوان السياسة",
                    purpose_en="", purpose_ar="",
                    clauses=(("Write your Policy here", "اكتب السياسة هنا"),),
                    numbered=True):
	"""The real template's shape: spacer, title, approval matrix, Purpose, clauses.

	Plus the header's NESTED 2x1 title — the one a body-only walk misses.
	"""
	build = _Builder()
	item_rows = []
	for position, (english, arabic) in enumerate(clauses, start=1):
		number = str(position) if numbered else ""
		item_rows.append([number, english, arabic,
		                  gdocs._arabic_indic(position) if numbered else ""])
	body = [
		build.table([["", ""]]),                                   # empty spacer
		build.table([[title_en, title_ar]]),                       # body title
		build.table([["Development & Approval Authority", "", "", "هيئة التطوير والاعتماد", "", ""],
		             ["Version", "Prepared By", "Reviewed By", "Approved By", "Notes", ""]]),
		build.table([["Purpose:", "الغرض:"], [purpose_en, purpose_ar]]),
		build.table([["Policy:", "", "السياسة:", ""]] + item_rows),
	]
	header_build = _Builder()
	inner = header_build.table([[title_ar], [title_en]])
	header_table = header_build.table([["", "", ""]], nested=(0, 1, inner))
	return {
		"documentId": DOC_ID,
		"body": {"content": body},
		"headers": {HEADER_SEGMENT: {"content": [header_table]}},
		"footers": {"ftr.default": {"content": [
			_Builder().table([["Page:", "", "صفحة:"]])]}},
	}


class _FillCase(unittest.TestCase):
	"""Captures the batches a fill would send, without sending them."""

	def fill(self, content, document=None):
		state = document or policy_document()
		self.batches = []

		def fake_get(_document_id):
			return state

		def fake_batch(_document_id, requests):
			self.batches.append(requests)
			# Row edits are applied to the fake, because the code re-reads the
			# document after resizing the table and the second read has to show
			# the new rows — a fake that ignored them would make the numbering
			# test pass for the wrong reason.
			layout = gdocs._find_item_table(state)
			for request in requests:
				if "insertTableRow" in request and layout:
					rows = gdocs._rows(layout["table"])
					width = len(gdocs._cells(rows[0]))
					rows.append({"tableCells": [_Builder().cell("") for _ in range(width)]})
					layout["table"]["table"]["rows"] = len(rows)
				elif "deleteTableRow" in request and layout:
					index = request["deleteTableRow"]["tableCellLocation"]["rowIndex"]
					rows = gdocs._rows(layout["table"])
					if 0 <= index < len(rows):
						rows.pop(index)
					layout["table"]["table"]["rows"] = len(rows)
			return {"replies": [{} for _ in requests]}

		with patch.object(gdocs, "get_document", side_effect=fake_get), \
		     patch.object(gdocs, "batch_update", side_effect=fake_batch):
			return gdocs.fill_branded_template(DOC_ID, content)

	@property
	def writes(self):
		return [r for batch in self.batches for r in batch]

	def inserted(self, segment=None):
		return [r["insertText"] for r in self.writes if "insertText" in r
		        and (segment is None or (r["insertText"]["location"].get("segmentId") or "") == segment)]

	def inserted_text(self, segment=None):
		return [i["text"] for i in self.inserted(segment)]


class TestTheTitleReachesEverySlot(_FillCase):
	"""The bug that published a Policy saying "Add  the title of the Policy"."""

	def test_the_header_title_is_filled_not_only_the_body_one(self):
		report = self.fill({"title": "Leave Policy", "title_ar": "سياسة الإجازات"})
		self.assertEqual(report["filled"]["title_slots"], 2,
		                 "the body title and the running-header title are the same title")
		self.assertEqual(self.inserted_text("").count("Leave Policy"), 1)
		self.assertEqual(self.inserted_text(HEADER_SEGMENT).count("Leave Policy"), 1)

	def test_a_header_edit_names_its_segment(self):
		"""Header content has its own index space; an unsegmented edit lands in
		the body, at whatever happens to be at that index."""
		self.fill({"title": "Leave Policy", "title_ar": "سياسة الإجازات"})
		header_edits = [r for r in self.writes
		                if (r.get("insertText") or {}).get("location", {}).get("segmentId")
		                == HEADER_SEGMENT]
		self.assertTrue(header_edits, "nothing was addressed to the header segment")
		for request in self.writes:
			for key, field in (("insertText", "location"), ("deleteContentRange", "range")):
				if key in request:
					self.assertIn("segmentId", request[key][field],
					              "every edit must state which segment it belongs to")

	def test_the_nested_header_table_is_reached_at_all(self):
		"""The header title is a table inside a table cell. A walker that does not
		recurse simply never sees it."""
		document = policy_document()
		found = list(gdocs._iter_tables(document))
		self.assertIn(HEADER_SEGMENT, [segment for segment, _ in found])
		two_cell = [element for segment, element in found
		            if sum(len(gdocs._cells(row)) for row in gdocs._rows(element)) == 2]
		self.assertEqual(len(two_cell), 3,
		                 "spacer, body title and nested header title are all 2-cell tables")

	def test_english_and_arabic_are_told_apart_by_script_not_by_position(self):
		"""The body pair is (EN, AR) and the header pair is (AR, EN). Position is
		not a usable rule; script is."""
		report = self.fill({"title": "Leave Policy", "title_ar": "سياسة الإجازات"})
		self.assertEqual(report["unmatched"], [])
		for segment in ("", HEADER_SEGMENT):
			texts = self.inserted_text(segment)
			self.assertIn("Leave Policy", texts)
			self.assertIn("سياسة الإجازات", texts)

	def test_the_empty_spacer_table_is_not_mistaken_for_a_title(self):
		"""Every template opens with an empty 1x2 table. Writing the title there
		would put it above the letterhead."""
		self.fill({"title": "Leave Policy", "title_ar": "سياسة الإجازات"})
		self.assertEqual(len(self.inserted_text("")), 2, "one EN and one AR cell in the body")


class TestNumbering(_FillCase):
	"""The Arabic-Indic digit bug."""

	def test_arabic_indic_digits_are_not_treated_as_the_latin_column(self):
		# The trap itself, asserted directly: this is why str.isdigit() cannot be
		# used to find the Latin numbering column.
		self.assertTrue("١".isdigit())
		self.assertFalse(gdocs._is_latin_number("١"))
		self.assertTrue(gdocs._is_latin_number("1"))
		self.assertTrue(gdocs._is_arabic_number("١"))
		self.assertFalse(gdocs._is_arabic_number("1"))

	def test_the_two_numbering_columns_are_found_separately(self):
		layout = gdocs._find_item_table(policy_document())
		self.assertEqual(layout["num"], 0)
		self.assertEqual(layout["en"], 1)
		self.assertEqual(layout["ar"], 2)
		self.assertEqual(layout["num_ar"], 3,
		                 "collapsing these two columns wrote the number into the wrong one")

	def test_added_rows_are_numbered_in_both_scripts(self):
		report = self.fill({"items": [{"en": "One.", "ar": "واحد."},
		                              {"en": "Two.", "ar": "اثنان."},
		                              {"en": "Three.", "ar": "ثلاثة."}]})
		self.assertEqual(report["rows_added"], 2)
		texts = self.inserted_text("")
		for latin, arabic in (("2", "٢"), ("3", "٣")):
			self.assertIn(latin, texts)
			self.assertIn(arabic, texts)

	def test_arabic_indic_conversion_handles_more_than_one_digit(self):
		self.assertEqual(gdocs._arabic_indic(1), "١")
		self.assertEqual(gdocs._arabic_indic(10), "١٠")
		self.assertEqual(gdocs._arabic_indic(13), "١٣")


class TestTheItemTableIsSizedToTheContent(_FillCase):
	"""The template ships one example row; a real policy has many clauses."""

	def test_rows_are_added_when_there_are_more_clauses_than_rows(self):
		report = self.fill({"items": [{"en": "a", "ar": "أ"}] * 4})
		self.assertEqual(report["rows_added"], 3)
		self.assertEqual(report["rows_removed"], 0)

	def test_rows_are_removed_when_a_revision_is_shorter(self):
		document = policy_document(clauses=(("one", "١"), ("two", "٢"), ("three", "٣")))
		report = self.fill({"items": [{"en": "only", "ar": "فقط"}]}, document=document)
		self.assertEqual(report["rows_removed"], 2)
		self.assertEqual(report["rows_added"], 0)

	def test_surplus_rows_are_deleted_bottom_up(self):
		"""Deleting a row renumbers everything below it, so top-down deletion
		removes the wrong rows."""
		document = policy_document(clauses=(("one", "١"), ("two", "٢"), ("three", "٣")))
		self.fill({"items": [{"en": "only", "ar": "فقط"}]}, document=document)
		deletions = [r["deleteTableRow"]["tableCellLocation"]["rowIndex"]
		             for r in self.writes if "deleteTableRow" in r]
		self.assertEqual(deletions, sorted(deletions, reverse=True))

	def test_row_edits_do_not_share_a_batch_with_content_edits(self):
		"""Adding a row moves every index after it, invalidating indices computed
		before the batch was built."""
		self.fill({"title": "T", "title_ar": "ع",
		           "items": [{"en": "a", "ar": "أ"}, {"en": "b", "ar": "ب"}]})
		self.assertGreaterEqual(len(self.batches), 2)
		structural = [i for i, batch in enumerate(self.batches)
		              if any("insertTableRow" in r or "deleteTableRow" in r for r in batch)]
		textual = [i for i, batch in enumerate(self.batches)
		           if any("insertText" in r for r in batch)]
		self.assertTrue(structural and textual)
		self.assertTrue(max(structural) < min(textual),
		                "the table must be resized before any index is computed")


class TestRefillingReplacesRatherThanAppends(_FillCase):
	"""What an Update does: fill a document that has already been filled."""

	def test_existing_cell_text_is_cleared_before_the_new_text_is_written(self):
		document = policy_document(title_en="Old Title", title_ar="العنوان القديم",
		                           purpose_en="Old purpose.", purpose_ar="غرض قديم.")
		self.fill({"title": "New Title", "title_ar": "العنوان الجديد",
		           "sections": {"Purpose": "New purpose."}}, document=document)
		self.assertTrue([r for r in self.writes if "deleteContentRange" in r],
		                "without a clear, revision 2 is appended to revision 1")

	def test_a_cleared_range_stops_short_of_the_paragraph_mark(self):
		"""Docs rejects a delete that would remove a cell's final newline."""
		document = policy_document(title_en="Old Title", title_ar="العنوان القديم")
		self.fill({"title": "New", "title_ar": "جديد"}, document=document)
		for request in self.writes:
			if "deleteContentRange" in request:
				span = request["deleteContentRange"]["range"]
				self.assertLess(span["startIndex"], span["endIndex"])

	def test_an_empty_cell_is_written_without_a_delete_for_it(self):
		document = policy_document(purpose_en="", purpose_ar="")
		self.fill({"sections": {"Purpose": "Fresh."}}, document=document)
		self.assertIn("Fresh.", self.inserted_text(""))

	def test_edits_are_applied_from_the_bottom_of_the_document_upwards(self):
		"""Each edit changes the length of the document, so anything below it must
		already have been applied."""
		self.fill({"title": "T", "title_ar": "ع",
		           "sections": {"Purpose": "P", "الغرض": "غ"},
		           "items": [{"en": "a", "ar": "أ"}]})
		positions = [r["insertText"]["location"]["index"] for r in self.writes
		             if "insertText" in r]
		self.assertEqual(positions, sorted(positions, reverse=True))


class TestSectionsAndIntro(_FillCase):
	"""Where labelled content goes, and how Manual differs."""

	def test_content_goes_below_the_label_not_into_the_adjacent_label(self):
		"""In "Purpose: | الغرض:" the cell beside the English label is the ARABIC
		LABEL. Writing there would overwrite the template's own wording."""
		document = policy_document()
		segment, cell = gdocs._find_section_cell(document, "Purpose")
		self.assertEqual(segment, "")
		self.assertEqual(gdocs._cell_text(cell), "")
		self.assertIsNot(cell, gdocs._cells(gdocs._rows(document["body"]["content"][3])[0])[1])

	def test_the_label_is_matched_without_its_colon_and_ignoring_case(self):
		document = policy_document()
		for spelling in ("Purpose", "purpose", "Purpose:", "  PURPOSE:  "):
			with self.subTest(spelling=spelling):
				self.assertIsNotNone(gdocs._find_section_cell(document, spelling))

	def test_the_arabic_label_finds_its_own_cell(self):
		document = policy_document()
		english = gdocs._find_section_cell(document, "Purpose")[1]
		arabic = gdocs._find_section_cell(document, "الغرض")[1]
		self.assertIsNotNone(arabic)
		self.assertIsNot(english, arabic, "each language has its own cell")

	def test_a_heading_ending_in_a_colon_is_not_an_intro_slot(self):
		"""Policy's clause table opens with "Policy:" — a heading. Manual's opens
		with "EXPLAIN WHAT THIS MANUAL IS ABOUT" — a slot. The colon is the tell,
		and treating Policy's heading as a slot would overwrite it."""
		layout = gdocs._find_item_table(policy_document())
		self.assertEqual(gdocs._find_intro_cells(layout), (None, None))

	def test_a_manual_style_opening_statement_is_an_intro_slot(self):
		document = policy_document()
		table = document["body"]["content"][4]["table"]
		cells = table["tableRows"][0]["tableCells"]
		cells[0]["content"][0]["paragraph"]["elements"] = [
			{"textRun": {"content": "EXPLAIN WHAT THIS MANUAL IS ABOUT"}}]
		cells[2]["content"][0]["paragraph"]["elements"] = [
			{"textRun": {"content": "اشرح ما الذي يدور حوله هذا الدليل"}}]
		layout = gdocs._find_item_table(document)
		english, arabic = gdocs._find_intro_cells(layout)
		self.assertIsNotNone(english)
		self.assertIsNotNone(arabic)


class TestNothingIsSwallowed(_FillCase):
	"""A miss must be reported, because a miss is a visible defect."""

	def test_a_section_the_template_does_not_have_is_reported(self):
		report = self.fill({"sections": {"Definitions": "Terms."}})
		self.assertIn("section:Definitions", report["unmatched"])

	def test_a_template_with_no_numbered_table_is_reported(self):
		document = policy_document()
		document["body"]["content"].pop(4)
		report = self.fill({"items": [{"en": "a", "ar": "أ"}]}, document=document)
		self.assertTrue(any(u.startswith("items:") for u in report["unmatched"]))

	def test_a_clean_fill_reports_nothing_unmatched(self):
		"""So that a non-empty unmatched list is a real alarm rather than noise."""
		report = self.fill({"title": "T", "title_ar": "ع",
		                    "sections": {"Purpose": "P", "الغرض": "غ"},
		                    "items": [{"en": "a", "ar": "أ"}]})
		self.assertEqual(report["unmatched"], [])

	def test_blank_values_are_skipped_rather_than_clearing_a_cell(self):
		report = self.fill({"title": "T", "title_ar": "ع",
		                    "sections": {"Purpose": "", "الغرض": "   "}})
		self.assertEqual(report["filled"].get("sections", 0), 0)
		self.assertEqual(report["unmatched"], [])

	def test_nothing_to_write_makes_no_api_call(self):
		report = self.fill({})
		self.assertEqual(self.batches, [])
		self.assertEqual(report["rows_added"], 0)


class TestTheConnectorOperation(unittest.TestCase):
	"""The BPMN-facing wrapper — the parts that need no database."""

	def _call(self, params, result):
		from one_bpmn.one_bpmn.connectors import google_docs_ops as ops
		with patch.object(gdocs, "fill_branded_template", return_value=result):
			return ops.fill_branded_template(params, None)

	def test_content_may_arrive_as_a_json_string(self):
		"""It normally does: connectorParams values are Jinja-rendered strings."""
		captured = {}

		def fake(document_id, content):
			captured["content"] = content
			return {"filled": {}, "unmatched": []}

		from one_bpmn.one_bpmn.connectors import google_docs_ops as ops
		with patch.object(gdocs, "fill_branded_template", side_effect=fake):
			ops.fill_branded_template(
				{"document": DOC_ID, "content": '{"title": "T", "items": []}'}, None)
		self.assertEqual(captured["content"]["title"], "T")

	def test_a_non_object_payload_is_rejected_with_a_useful_message(self):
		from one_bpmn.one_bpmn.connectors import google_docs_ops as ops
		with self.assertRaises(ValueError) as caught:
			ops.fill_branded_template({"document": DOC_ID, "content": '["not", "an", "object"]'}, None)
		self.assertIn("title", str(caught.exception))

	def test_unmatched_targets_do_not_fail_the_task_by_default(self):
		"""Unlike fillTemplate. The three templates genuinely differ, so a section
		a type does not own is expected rather than broken."""
		result = self._call({"document": DOC_ID, "content": "{}"},
		                    {"filled": {}, "unmatched": ["section:Laws"]})
		self.assertEqual(result["unmatched"], ["section:Laws"])

	def test_the_check_can_be_demanded(self):
		with self.assertRaises(ValueError):
			self._call({"document": DOC_ID, "content": "{}", "failIfUnmatched": "true"},
			           {"filled": {}, "unmatched": ["section:Laws"]})

class TestTheOperationIsDeclared(FrappeTestCase):
	"""That the modeler can actually offer it. Needs the site database."""

	def test_the_operation_is_registered_against_a_real_handler(self):
		import importlib
		name = frappe.db.get_value(
			"BPMN Connector Operation",
			{"connector": "google_docs", "operation_id": "fillBrandedTemplate"},
			"name")
		self.assertTrue(name, "the modeler cannot offer an operation that is not declared")
		row = frappe.get_doc("BPMN Connector Operation", name)
		self.assertEqual(row.execution_type, "Python Handler")
		module_path, _, attribute = row.handler_path.rpartition(".")
		self.assertTrue(hasattr(importlib.import_module(module_path), attribute),
		                "handler_path must point at something importable")

	def test_the_declared_fields_match_what_the_handler_reads(self):
		name = frappe.db.get_value(
			"BPMN Connector Operation",
			{"connector": "google_docs", "operation_id": "fillBrandedTemplate"}, "name")
		fields = {row.field_name for row in frappe.get_doc(
			"BPMN Connector Operation", name).get("fields")}
		self.assertEqual(fields, {"document", "content", "failIfUnmatched"})

