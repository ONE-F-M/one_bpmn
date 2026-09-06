# Copyright (c) 2026, one-fm and contributors
"""A Lucidchart document is fetched once per conversation.

Every chat turn is a fresh run, so the parse never outlived the turn that paid
for it — the same document was fetched ten times in twelve sampled runs. The full
parse now lives in the conversation's session state, and a repeat request gets a
short marker instead of the body. These tests drive the real tool script through
the shape runner with the cache seeded, so no call reaches Lucidchart.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_lucrusher_fetch_cache
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import session_state
from one_bpmn.agents.shape_tools import execute_shape
from one_bpmn.one_bpmn.patches.v1_0.lucrusher_fetches_a_document_once import (
	MARK,
	SCRIPT,
	execute,
)

DOC_ID = "0f0f0f0f-1111-2222-3333-444444444444"
URL = f"https://lucid.app/lucidchart/{DOC_ID}/edit?page=abc"

FULL_DOC = {
	"document_id": DOC_ID,
	"title": "Subcontractor Payment",
	"page_count": 2,
	"total_shapes": 40,
	"total_lines": 38,
	"content_api_status": "ok",
	"summary": "A two-page process.",
	"error": None,
	"pages": [
		{
			"page_title": "Request",
			"shape_count": 25,
			"line_count": 24,
			"process_steps": [{"text": f"Step {i}"} for i in range(1, 13)],
			"decisions": [{"text": "Approved?"}],
			"connections": [],
			"annotations": [],
			"swimlanes": [],
			"terminators": [],
			"raw_shapes": [{"id": i} for i in range(25)],
		},
		{
			"page_title": "Payment",
			"shape_count": 15,
			"line_count": 14,
			"process_steps": [{"text": "Pay"}],
			"decisions": [],
			"connections": [],
			"annotations": [],
			"swimlanes": [],
			"terminators": [],
			"raw_shapes": [],
		},
	],
}


class TestFetchOncePerConversation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Server Script", SCRIPT):
			raise frappe.tests.utils.SkipTest(f"{SCRIPT} is not installed")  # pragma: no cover

	def setUp(self):
		super().setUp()
		self.conversation = frappe.get_doc({
			"doctype": "Chat Conversation",
			"title": "_lucrusher cache test",
		}).insert(ignore_permissions=True)
		# Session state commits on create, so it outlives the rollback.
		self.addCleanup(self._drop)
		self.instance = SimpleNamespace(
			name="INST-LCR",
			context_doctype="Chat Conversation",
			context_docname=self.conversation.name,
			_service_task_extensions={},
		)

	def _drop(self):
		for dt, name in (("Chat Session State", self.conversation.name), ("Chat Conversation", self.conversation.name)):
			if frappe.db.exists(dt, name):
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _fetch(self, text):
		out = execute_shape(
			self.instance,
			"fetch_lucidchart_document",
			{"serverScript": SCRIPT},
			{"document_id_or_url": text},
		)
		return json.loads(out)["document"]

	def _seed(self):
		session_state.record(self.conversation.name, {"lucid_doc:" + DOC_ID: FULL_DOC})

	def test_a_repeat_request_gets_the_marker_not_the_body(self):
		self._seed()

		doc = self._fetch(URL)

		self.assertTrue(doc["already_fetched"])
		self.assertEqual(doc["title"], "Subcontractor Payment")
		self.assertEqual([p["title"] for p in doc["pages"]], ["Request", "Payment"])
		self.assertNotIn("process_steps", json.dumps(doc))
		# The marker is a fixed few hundred bytes whatever the document weighs;
		# the body it replaces was ~30 kB on the runs that motivated this.
		self.assertLess(len(json.dumps(doc)), 1024)

	def test_the_marker_says_how_to_drill_down(self):
		self._seed()

		doc = self._fetch(DOC_ID)

		self.assertIn("#page=<n>", doc["note"])
		self.assertIn("#refresh", doc["note"])

	def test_a_page_comes_back_in_full_from_the_cache(self):
		"""The trimmed first view caps a page at eight steps; the drill-down is
		the whole page, minus the raw shape dump the model never needs."""
		self._seed()

		doc = self._fetch(f"{URL}#page=1")

		self.assertEqual(doc["page"], 1)
		self.assertEqual(len(doc["detail"]["process_steps"]), 12)
		self.assertNotIn("raw_shapes", doc["detail"])

	def test_a_page_that_does_not_exist_is_an_error_not_a_crash(self):
		self._seed()

		doc = self._fetch(f"{DOC_ID}#page=9")

		self.assertIn("does not exist", doc["error"])

	def test_finalize_still_receives_the_full_parse_on_a_hit(self):
		"""The frontend gets the document from finalize, which reads the turn
		store. A cache hit must fill it exactly as a fetch would."""
		from one_bpmn.agents.turn_state import get_turn, set_turn

		self._seed()
		set_turn(self.conversation.name, {})

		self._fetch(URL)

		stored = get_turn(self.conversation.name).get("full_document")
		self.assertEqual(stored["title"], "Subcontractor Payment")
		self.assertEqual(len(stored["pages"][0]["raw_shapes"]), 25)

	def test_an_unparseable_reference_is_neither_fetched_nor_cached(self):
		doc = self._fetch("https://lucid.app/lucidchart/not-a-real-id/edit")

		self.assertTrue(doc["error"])
		self.assertEqual(session_state.get_state(self.conversation.name), {})


class TestThePatch(FrappeTestCase):
	def test_the_live_script_carries_the_cache(self):
		if not frappe.db.exists("Server Script", SCRIPT):
			self.skipTest(f"{SCRIPT} is not installed")
		self.assertIn(MARK, frappe.db.get_value("Server Script", SCRIPT, "script") or "")

	def test_running_it_again_changes_nothing(self):
		if not frappe.db.exists("Server Script", SCRIPT):
			self.skipTest(f"{SCRIPT} is not installed")
		before = frappe.db.get_value("Server Script", SCRIPT, "script")

		execute()

		self.assertEqual(frappe.db.get_value("Server Script", SCRIPT, "script"), before)

	def test_the_patch_is_declared(self):
		patches = open(os.path.join(frappe.get_app_path("one_bpmn"), "patches.txt")).read()
		self.assertIn("one_bpmn.one_bpmn.patches.v1_0.lucrusher_fetches_a_document_once", patches)
		self.assertIn("one_bpmn.one_bpmn.patches.v1_0.record_tool_artifacts", patches)
