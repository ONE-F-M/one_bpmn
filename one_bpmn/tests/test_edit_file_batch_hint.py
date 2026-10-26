# Copyright (c) 2026, one-fm and contributors
"""A changed edit_file result tells the model to batch what it already knows, and the stored result stays as the sandbox sent it."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops


class TestEditFileBatchHint(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _dispatch(self, action, answer):
		class _Response:
			headers = {}
			status_code = 200

			def raise_for_status(self):
				return None

			def json(self):
				return dict(answer)

		with patch.object(ops, "_mint_identity_token", return_value="t"), patch("requests.post", return_value=_Response()):
			return ops.sandbox_dispatch(action, "one_fm", "staging", "Fix it.", {"path": "a.py"})

	def test_a_changed_edit_file_carries_the_hint(self):
		result = self._dispatch("edit_file", {"edited": "a.py"})
		self.assertTrue(result["ok"])
		self.assertIn("apply_edits", result["response"]["hint"])
		self.assertEqual(result["response"]["edited"], "a.py")

	def test_an_edit_file_that_changed_nothing_carries_no_hint(self):
		result = self._dispatch("edit_file", {"error": "old_string not found in the file"})
		self.assertNotIn("hint", result["response"])

	def test_apply_edits_carries_no_hint(self):
		result = self._dispatch("apply_edits", {"applied": 3})
		self.assertNotIn("hint", result["response"])

	def test_the_stored_result_is_what_the_sandbox_sent(self):
		self._dispatch("edit_file", {"edited": "a.py"})
		stored = frappe.parse_json(frappe.get_last_doc("Agent Sandbox Run").result)
		self.assertNotIn("hint", stored)
