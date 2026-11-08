"""Tests for signed attachment links.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_attachment_links
"""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

_TEST_SECRET = "test-secret-key-for-unit-tests"
_CONTENT = b"attachment body"


def _expired(token: str) -> str:
	"""Re-sign the token's payload with an expiry in the past."""
	from one_bpmn.utils.token import _sign

	payload = json.loads(base64.urlsafe_b64decode(token.rsplit(".", 1)[0].encode("ascii")))
	payload["expires"] = int(time.time()) - 3600
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded}.{_sign(payload_json)}"


class TestAttachmentLinks(FrappeTestCase):
	def setUp(self):
		patcher = patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET)
		patcher.start()
		self.addCleanup(patcher.stop)

		frappe.local.response = frappe._dict()
		self.todo = self._make_todo("attachment link test")
		self.other = self._make_todo("other document")
		self.file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "supporting.txt",
				"content": _CONTENT,
				"is_private": 1,
				"attached_to_doctype": "ToDo",
				"attached_to_name": self.todo.name,
			}
		).insert()

	def _make_todo(self, description):
		return frappe.get_doc(
			{"doctype": "ToDo", "description": description, "allocated_to": "Administrator"}
		).insert()

	def _token(self, **overrides):
		from one_bpmn.utils.token import generate_file_token

		args = {"file_name": self.file.name, "doctype": "ToDo", "docname": self.todo.name, "expiry_hours": 1}
		args.update(overrides)
		return generate_file_token(**args)

	def _download(self, token):
		from one_bpmn.api.todo_actions import download_attachment

		return download_attachment(token)

	def _assert_nothing_served(self):
		self.assertNotIn("filecontent", frappe.local.response)
		self.assertNotEqual(frappe.local.response.get("type"), "download")

	def test_build_attachment_links(self):
		from one_bpmn.email_builder.fields import build_attachment_links

		links = build_attachment_links(self.todo, 1)
		self.assertEqual(len(links), 1)
		self.assertEqual(links[0]["file_name"], "supporting.txt")

		token = parse_qs(urlparse(links[0]["url"]).query)["token"][0]
		self._download(token)
		self.assertEqual(frappe.local.response.filename, "supporting.txt")

		self.assertEqual(build_attachment_links(self.other, 1), [])

	def test_valid_download(self):
		self._download(self._token())
		self.assertEqual(frappe.local.response.type, "download")
		self.assertEqual(frappe.local.response.filename, "supporting.txt")
		self.assertEqual(frappe.safe_encode(frappe.local.response.filecontent), _CONTENT)

	def test_expired_token(self):
		self._download(_expired(self._token()))
		self.assertEqual(frappe.local.response.get("type"), "page")
		self.assertEqual(frappe.local.response.get("http_status_code"), 410)
		self.assertIn("expired", frappe.local.message)
		self.assertIn("Open in ERPNext", frappe.local.message)
		self.assertIn(self.todo.name, frappe.local.message)
		self._assert_nothing_served()

	def test_tampered_token(self):
		with self.assertRaises(frappe.PermissionError):
			self._download(self._token()[:-4] + "XXXX")
		self._assert_nothing_served()

	def test_malformed_and_missing_token(self):
		for token in ("", "not-a-token", "abc.def"):
			with self.assertRaises(frappe.PermissionError):
				self._download(token)
		self._assert_nothing_served()

	def test_detached_file(self):
		token = self._token()
		frappe.db.set_value("File", self.file.name, "attached_to_name", self.other.name)
		with self.assertRaises(frappe.PermissionError):
			self._download(token)
		self._assert_nothing_served()

	def test_token_for_another_document(self):
		with self.assertRaises(frappe.PermissionError):
			self._download(self._token(docname=self.other.name))
		self._assert_nothing_served()

	def test_wrong_token_type(self):
		from one_bpmn.utils.token import (
			generate_action_token,
			generate_conversation_token,
			generate_status_token,
		)

		tokens = (
			generate_action_token("INST-1", "t1", "Approve", "user@test.com"),
			generate_status_token("INST-1", "t1"),
			generate_conversation_token("INST-1", "t1", "user@test.com", "thread"),
		)
		for token in tokens:
			with self.assertRaises(frappe.PermissionError):
				self._download(token)
		self._assert_nothing_served()
