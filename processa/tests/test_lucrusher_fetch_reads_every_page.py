# Copyright (c) 2026, one-fm and contributors
"""LuCrusher reads a link-shared Lucidchart file and every page of it, or says why it could not.

The tests drive the real fetch tool script through the shape runner, as the fetch-once
cache tests do, with every Lucidchart call answered by a stand-in. They skip on a site
whose tool script predates share link acceptance, since the script ships by map export.

Run with:
    bench --site SITE run-tests --app processa --module processa.tests.test_lucrusher_fetch_reads_every_page
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_conversations import session_state
from processa.ai_agent_skills.tools.shape_tools import execute_shape
from processa.patches.v1_0.lucrusher_fetches_a_document_once import SCRIPT

DOC_ID = "5a5a5a5a-1111-2222-3333-444444444444"
SHARE_LINK = "inv_6b6b6b6b-1111-2222-3333-444444444444"
PUBLIC_URL = f"https://lucid.app/lucidchart/{DOC_ID}/edit?invitationId={SHARE_LINK}"
PLAIN_URL = f"https://lucid.app/lucidchart/{DOC_ID}/edit"
ACCEPT_PATH = f"/v1/shareLink/{SHARE_LINK}/accept"
META_PATH = f"/documents/{DOC_ID}"
CONTENT_PATH = f"/v1/documents/{DOC_ID}/contents"


def _page(n: int) -> dict:
	return {
		"id": f"page-{n}",
		"title": f"Step {n}",
		"items": {
			"shapes": [{"id": f"s{n}", "class": "ProcessBlock", "textAreas": [{"text": f"Do {n}"}]}],
			"lines": [],
		},
	}


class _Lucid:
	"""Answers each Lucidchart path with a JSON body, or fails it with an HTTP status."""

	def __init__(self, answers: dict):
		self.answers = answers
		self.posted = []

	def _answer(self, url):
		for path, answer in self.answers.items():
			if url.endswith(path):
				if callable(answer):
					answer = answer()
				if isinstance(answer, int):
					frappe.flags.integration_request = SimpleNamespace(status_code=answer, text="")
					raise Exception(f"HTTP {answer}")
				return answer
		frappe.flags.integration_request = SimpleNamespace(status_code=404, text="")
		raise Exception("HTTP 404")

	def get(self, url, **kwargs):
		return self._answer(url)

	def post(self, url, **kwargs):
		self.posted.append(url)
		return self._answer(url)


class TestLucrusherReadsEveryPage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		script = frappe.db.get_value("Server Script", SCRIPT, "script") or ""
		if "/v1/shareLink/" not in script:
			raise unittest.SkipTest(f"{SCRIPT} on this site predates share link acceptance")

	def setUp(self):
		super().setUp()
		self.conversation = frappe.get_doc(
			{"doctype": "Chat Conversation", "title": "_lucrusher every page test"}
		).insert()
		self.addCleanup(self._drop)
		self.instance = SimpleNamespace(
			name="INST-LCR-PAGES",
			context_doctype="Chat Conversation",
			context_docname=self.conversation.name,
			_service_task_extensions={},
		)
		conf = patch.dict(frappe.local.conf, {"lucidchart_api_key": "test-key"})
		conf.start()
		self.addCleanup(conf.stop)

	def _drop(self):
		for dt, name in (
			("Chat Session State", self.conversation.name),
			("Chat Conversation", self.conversation.name),
		):
			if frappe.db.exists(dt, name):
				frappe.delete_doc(dt, name, force=True)
		frappe.db.commit()

	def _fetch(self, url: str, answers: dict) -> tuple[dict, _Lucid]:
		lucid = _Lucid({"/users/me/profile": {"email": "platform@example.com"}, **answers})
		with (
			patch("frappe.integrations.utils.make_get_request", side_effect=lucid.get),
			patch("frappe.integrations.utils.make_post_request", side_effect=lucid.post),
			patch("time.sleep"),
		):
			out = execute_shape(
				self.instance,
				"fetch_lucidchart_document",
				{"serverScript": SCRIPT},
				{"document_id_or_url": url},
			)
		return json.loads(out)["document"], lucid

	def _cached(self):
		return session_state.get_state(self.conversation.name).get("lucid_doc:" + DOC_ID)

	def test_a_link_shared_file_is_read_after_accepting_its_share_link(self):
		accepted = []

		def accept():
			accepted.append(True)
			return {"InvitationType": "document", "DocumentIdOpt": DOC_ID}

		doc, lucid = self._fetch(
			PUBLIC_URL,
			{
				META_PATH: lambda: {"title": "Client Event", "pageCount": 2} if accepted else 403,
				ACCEPT_PATH: accept,
				CONTENT_PATH: {"pages": [_page(1), _page(2)]},
			},
		)

		self.assertFalse(doc.get("error"))
		self.assertEqual(doc["page_count"], 2)
		self.assertTrue(lucid.posted[0].endswith(ACCEPT_PATH))

	def test_a_share_link_limited_to_the_owners_account_says_so(self):
		doc, lucid = self._fetch(PUBLIC_URL, {META_PATH: 403, ACCEPT_PATH: {"InvitationType": "document"}})

		self.assertIn("I accepted the Lucidchart share link", doc["error"])
		self.assertIn("platform@example.com", doc["error"])
		self.assertNotIn("Copy link", doc["error"])
		self.assertEqual(len(lucid.posted), 1)

	def test_an_expired_share_link_says_to_copy_a_fresh_one(self):
		doc, lucid = self._fetch(PUBLIC_URL, {META_PATH: 403, ACCEPT_PATH: 404})

		self.assertIn("expired", doc["error"])
		self.assertTrue(lucid.posted[0].endswith(ACCEPT_PATH))
		self.assertIsNone(self._cached())

	def test_a_refused_share_link_names_the_access_needed(self):
		doc, _ = self._fetch(PUBLIC_URL, {META_PATH: 403, ACCEPT_PATH: 403})

		self.assertIn("ShareLinkAccept", doc["error"])
		self.assertIn("platform@example.com", doc["error"])

	def test_a_link_without_a_share_link_asks_for_one_or_for_sharing(self):
		doc, lucid = self._fetch(PLAIN_URL, {META_PATH: 403})

		self.assertIn("platform@example.com", doc["error"])
		self.assertIn("Copy link", doc["error"])
		self.assertEqual(lucid.posted, [])

	def test_a_five_page_file_reads_as_five_pages(self):
		doc, _ = self._fetch(
			PLAIN_URL,
			{
				META_PATH: {"title": "Client Event", "pageCount": 5},
				CONTENT_PATH: {"pages": [_page(n) for n in range(1, 6)]},
			},
		)

		self.assertFalse(doc.get("error"))
		self.assertEqual(doc["page_count"], 5)
		self.assertEqual(
			[p["page_title"] for p in self._cached()["pages"]], [f"Step {n}" for n in range(1, 6)]
		)

	def test_part_of_a_file_is_a_failure_and_not_kept(self):
		doc, _ = self._fetch(
			PLAIN_URL,
			{
				META_PATH: {"title": "Client Event", "pageCount": 5},
				CONTENT_PATH: {"pages": [_page(1), _page(2), _page(3)]},
			},
		)

		self.assertIn("sent 3 of the document's 5 pages", doc["error"])
		self.assertIsNone(self._cached())

	def test_pages_listed_without_their_content_are_a_failure(self):
		doc, _ = self._fetch(
			PLAIN_URL, {META_PATH: {"title": "Client Event", "pageCount": 5}, CONTENT_PATH: 500}
		)

		self.assertIn("listed 5 page(s)", doc["error"])
		self.assertIn("Nothing was read", doc["error"])
		self.assertIsNone(self._cached())

	def test_a_file_with_no_pages_is_a_failure_with_a_reason(self):
		doc, _ = self._fetch(
			PLAIN_URL, {META_PATH: {"title": "Empty", "pageCount": 0}, CONTENT_PATH: {"pages": []}}
		)

		self.assertIn("returned no pages", doc["error"])
		self.assertEqual(doc["page_count"], 0)
		self.assertIsNone(self._cached())
