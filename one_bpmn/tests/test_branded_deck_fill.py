# -*- coding: utf-8 -*-
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Filling the branded ONE-FM Guideline deck.

The Guideline template is a Google Slides deck, and almost nothing that makes
the Policy/SOP/Manual fill work applies to it. Every test here pins a decision
that was made because the deck differs, or a defect that the deck produced:

  * The deck SHIPS #TOKEN# placeholders, so the first fill could have been a
    find-and-replace — and a second one could not, because the tokens are gone
    by then. An Update has to revise the same Drive file, so targets are found
    by geometry and cleared before they are rewritten.
  * The Do's & Don'ts page uses the SAME layout as the content page, so the
    layout id cannot tell them apart. Only the content page carries a
    full-width body text box.
  * The guideline-name box and the page-title box are the same size and differ
    only in vertical position. Told apart any other way, every page ends up
    titled with the guideline's name.
  * The two Do's/Don'ts panels ship EMPTY. deleteText on an empty shape is an
    API error, so the clear has to be conditional.
  * "duplicateSlide" is not a Slides API request. The correct name is
    duplicateObject; the API rejects the payload outright, so a wrong name
    fails every fill rather than degrading quietly.

Nothing here touches the network: get_presentation and batch_update are faked
by a small stateful deck that applies duplicateObject and deleteObject, so the
structural pass is genuinely exercised rather than asserted about.
"""

import unittest
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.integrations import google_slides as gs
from one_bpmn.one_bpmn.connectors import google_slides_ops as ops

EMU = 914400
PID = "_TestGuidelineDeckCopy"


def _el(oid, kind, x, y, w, h, text=""):
    element = {
        "objectId": oid,
        "size": {"width": {"magnitude": w * EMU}, "height": {"magnitude": h * EMU}},
        "transform": {"translateX": x * EMU, "translateY": y * EMU,
                      "scaleX": 1, "scaleY": 1},
        "shape": {"shapeType": kind},
    }
    if text:
        element["shape"]["text"] = {"textElements": [{"textRun": {"content": text}}]}
    return element


class FakeDeck:
    """The real template's geometry, with duplicate/delete actually applied."""

    def __init__(self, content_pages=1):
        self.counter = 0
        self.cover = self._cover()
        self.contents = [self._content() for _ in range(content_pages)]
        self.dosdonts = self._dosdonts()
        self.requests = []

    def _oid(self, stem):
        self.counter += 1
        return f"{stem}_{self.counter}"

    def _cover(self):
        return {"objectId": self._oid("cover"), "slideProperties": {"layoutObjectId": "p2"},
                "pageElements": [
                    _el(self._oid("hero"), "ROUND_RECTANGLE", 0.34, 1.66, 9.32, 1.72, "#Guideline Name#"),
                    _el(self._oid("toc"), "ROUND_RECTANGLE", 4.30, 3.50, 5.36, 1.78,
                        "Table of Contents:\n#Page Title#\nDo’s & Don'ts"),
                    _el(self._oid("aside"), "ROUND_RECTANGLE", 0.34, 3.50, 3.82, 1.78, "Additional Info"),
                ]}

    def _content(self):
        return {"objectId": self._oid("page"), "slideProperties": {"layoutObjectId": "p4"},
                "pageElements": [
                    _el(self._oid("nm"), "ROUND_RECTANGLE", 0.12, 0.14, 6.38, 0.63, "#Guideline Name#"),
                    _el(self._oid("ti"), "ROUND_RECTANGLE", 0.12, 0.86, 6.38, 0.63, "#Page Title#"),
                    _el(self._oid("bd"), "TEXT_BOX", 0.01, 2.12, 9.79, 3.17, "#ENTER TEXT HERE#"),
                ]}

    def _dosdonts(self):
        return {"objectId": self._oid("dd"), "slideProperties": {"layoutObjectId": "p4"},
                "pageElements": [
                    _el(self._oid("nm"), "ROUND_RECTANGLE", 0.12, 0.14, 6.38, 0.63, "#Guideline Name#"),
                    _el(self._oid("hd"), "ROUND_RECTANGLE", 0.12, 0.86, 6.38, 0.63, "Do’s & Don'ts"),
                    # These two ship EMPTY.
                    _el(self._oid("dos"), "ROUND_RECTANGLE", 0.12, 1.69, 4.70, 3.78),
                    _el(self._oid("dnt"), "ROUND_RECTANGLE", 4.91, 1.69, 4.90, 3.78),
                    _el(self._oid("ldo"), "TEXT_BOX", 0.80, 1.69, 1.00, 0.57, "Do’s"),
                    _el(self._oid("ldn"), "TEXT_BOX", 5.44, 1.69, 1.17, 0.57, "Don’ts"),
                ]}

    # ── the faked integration surface ──────────────────────────────────────
    def get_presentation(self, presentation_id):
        return {"presentationId": presentation_id,
                "slides": [self.cover] + self.contents + [self.dosdonts]}

    def batch_update(self, presentation_id, requests):
        self.requests.extend(requests)
        for r in requests:
            if "duplicateObject" in r:
                self.contents.append(self._content())
            elif "deleteObject" in r:
                oid = r["deleteObject"]["objectId"]
                self.contents = [s for s in self.contents if s["objectId"] != oid]
        return {}

    def names(self):
        return [k for r in self.requests for k in r]

    def text_writes(self):
        return {r["insertText"]["objectId"]: r["insertText"]["text"]
                for r in self.requests if "insertText" in r}

    def cleared(self):
        return [r["deleteText"]["objectId"] for r in self.requests if "deleteText" in r]


CONTENT = {
    "guideline_name": "Site Access Control",
    "pages": [{"title": "Who may enter", "body": "Badge holders only."},
              {"title": "Visitors", "body": "Signed in at reception."}],
    "dos": ["Badge in every time."],
    "donts": ["Do not lend your badge."],
}


class TestBrandedDeckFill(FrappeTestCase):
    def _run(self, content=None, content_pages=1):
        deck = FakeDeck(content_pages=content_pages)
        with patch.object(gs, "get_presentation", side_effect=deck.get_presentation), \
             patch.object(gs, "batch_update", side_effect=deck.batch_update):
            report = gs.fill_branded_deck(PID, CONTENT if content is None else content)
        return deck, report

    # ── the structural pass ────────────────────────────────────────────────

    def test_duplicate_uses_duplicateObject_not_duplicateSlide(self):
        """The Slides API has no duplicateSlide; the wrong name 400s the batch."""
        deck, _ = self._run()
        self.assertIn("duplicateObject", deck.names())
        self.assertNotIn("duplicateSlide", deck.names())

    def test_deck_grows_to_one_page_per_entry(self):
        deck, report = self._run(content_pages=1)
        self.assertEqual(report["pages_added"], 1)
        self.assertEqual(len(deck.contents), 2)

    def test_surplus_pages_from_a_longer_revision_are_removed(self):
        deck, report = self._run(content_pages=5)
        self.assertEqual(report["pages_removed"], 3)
        self.assertEqual(len(deck.contents), 2)

    def test_an_exact_page_count_moves_nothing(self):
        deck, report = self._run(content_pages=2)
        self.assertEqual((report["pages_added"], report["pages_removed"]), (0, 0))
        self.assertNotIn("duplicateObject", deck.names())
        self.assertNotIn("deleteObject", deck.names())

    # ── telling the two p4 slides apart ────────────────────────────────────

    def test_dos_donts_page_is_not_mistaken_for_a_content_page(self):
        """Both use layout p4; only the content page has a full-width body."""
        deck = FakeDeck()
        self.assertTrue(gs._is_content_page(deck.contents[0]))
        self.assertFalse(gs._is_content_page(deck.dosdonts))
        self.assertTrue(gs._is_dos_donts_page(deck.dosdonts))
        self.assertFalse(gs._is_dos_donts_page(deck.contents[0]))

    def test_name_and_title_are_told_apart_by_vertical_position(self):
        deck = FakeDeck()
        slots = gs._content_slots(deck.contents[0])
        self.assertTrue(slots["name"].startswith("nm_"))
        self.assertTrue(slots["title"].startswith("ti_"))
        self.assertTrue(slots["body"].startswith("bd_"))

    def test_dos_is_the_left_panel_and_donts_the_right(self):
        deck = FakeDeck()
        slots = gs._dos_donts_slots(deck.dosdonts)
        self.assertTrue(slots["dos"].startswith("dos_"))
        self.assertTrue(slots["donts"].startswith("dnt_"))

    # ── the content pass ───────────────────────────────────────────────────

    def test_every_page_gets_its_own_title_and_body(self):
        deck, report = self._run()
        written = sorted(deck.text_writes().values())
        self.assertIn("Who may enter", written)
        self.assertIn("Visitors", written)
        self.assertIn("Badge holders only.", written)
        self.assertIn("Signed in at reception.", written)
        self.assertEqual(report["unmatched"], [])

    def test_a_populated_target_is_cleared_before_it_is_rewritten(self):
        """Without this, revision two is appended to revision one."""
        deck, _ = self._run()
        writes = deck.text_writes()
        title_id = next(k for k in writes if k.startswith("ti_"))
        self.assertIn(title_id, deck.cleared())

    def test_the_empty_dos_panels_are_not_cleared(self):
        """deleteText on a shape with no text is an API error."""
        deck, _ = self._run()
        cleared = deck.cleared()
        self.assertFalse([c for c in cleared if c.startswith(("dos_", "dnt_"))])
        self.assertTrue([k for k in deck.text_writes() if k.startswith("dos_")])

    def test_the_table_of_contents_is_rebuilt_from_the_page_titles(self):
        deck, _ = self._run()
        toc = next(v for k, v in deck.text_writes().items() if k.startswith("toc_"))
        self.assertTrue(toc.startswith("Table of Contents:"))
        self.assertIn("Who may enter", toc)
        self.assertIn("Visitors", toc)
        self.assertTrue(toc.rstrip().endswith("Don't" + "s"))

    def test_the_guideline_name_is_written_to_every_slide(self):
        deck, report = self._run()
        self.assertIn("cover.name", report["filled"])
        self.assertIn("page1.name", report["filled"])
        self.assertIn("dosdonts.name", report["filled"])

    # ── refusing to half-fill ──────────────────────────────────────────────

    def test_no_pages_writes_nothing_and_says_so(self):
        deck, report = self._run(content={"guideline_name": "X", "pages": []})
        self.assertEqual(report["unmatched"], ["pages:nothing to write"])
        self.assertEqual(deck.requests, [])

    def test_missing_dos_donts_page_is_reported_when_dos_were_supplied(self):
        deck = FakeDeck()
        deck.dosdonts = deck._content()          # no panels anywhere
        with patch.object(gs, "get_presentation", side_effect=deck.get_presentation), \
             patch.object(gs, "batch_update", side_effect=deck.batch_update):
            report = gs.fill_branded_deck(PID, CONTENT)
        self.assertTrue(any("dos/donts" in u for u in report["unmatched"]))

    # ── the connector handler ──────────────────────────────────────────────

    def test_handler_parses_content_arriving_as_a_json_string(self):
        import json
        with patch.object(gs, "fill_branded_deck", return_value={"unmatched": []}) as m:
            ops.fill_branded_deck({"presentation": PID, "content": json.dumps(CONTENT)}, None)
        self.assertEqual(m.call_args[0][1]["guideline_name"], "Site Access Control")

    def test_handler_rejects_content_that_is_not_an_object(self):
        with self.assertRaises(ValueError):
            ops.fill_branded_deck({"presentation": PID, "content": "[1, 2]"}, None)

    def test_handler_raises_on_unmatched_only_when_asked(self):
        with patch.object(gs, "fill_branded_deck", return_value={"unmatched": ["toc:not found"]}):
            ops.fill_branded_deck({"presentation": PID, "content": CONTENT}, None)
            with self.assertRaises(ValueError):
                ops.fill_branded_deck(
                    {"presentation": PID, "content": CONTENT, "failIfUnmatched": "1"}, None)
