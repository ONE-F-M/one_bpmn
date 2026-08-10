# Copyright (c) 2026, one-fm and contributors
# The Logix reply contract must reach the model on EVERY turn — the seeded
# agent prompt does not carry it, so build_logix_turn_context is its only
# delivery path. The CREATE-from-scratch turn (no linked script) regressed to
# prose replies (no onefm.script_diff card, no Apply button) when an early
# return skipped the contract; observed live on 2026-08-09.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.server_script_api import build_logix_turn_context

CONTRACT_MARKER = "LOGIX REPLY CONTRACT"


class TestLogixTurnContext(FrappeTestCase):
	def test_contract_present_without_linked_script(self):
		out = build_logix_turn_context({})
		self.assertIn(CONTRACT_MARKER, out.get("dialog_context", ""))
		self.assertNotIn("CURRENT SERVER SCRIPT", out["dialog_context"])
		self.assertNotIn("original_script_content", out)

	def test_contract_present_when_linked_script_missing(self):
		out = build_logix_turn_context({"current_script": "No Such Script"})
		self.assertEqual(out["current_script"], "")
		self.assertIn(CONTRACT_MARKER, out.get("dialog_context", ""))
		self.assertNotIn("CURRENT SERVER SCRIPT", out["dialog_context"])

	def test_existing_dialog_context_is_preserved(self):
		out = build_logix_turn_context({"dialog_context": "PRIOR CONTEXT"})
		self.assertTrue(out["dialog_context"].startswith("PRIOR CONTEXT"))
		self.assertIn(CONTRACT_MARKER, out["dialog_context"])

	def test_linked_script_content_rides_with_the_contract(self):
		script = frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": "Logix Turn Context Fixture",
				"script_type": "API",
				"api_method": "logix_turn_context_fixture",
				"script": "frappe.flags.logix_fixture = 1",
			}
		).insert(ignore_if_duplicate=True)
		out = build_logix_turn_context({"current_script": script.name})
		self.assertEqual(out["original_script_content"], script.script)
		self.assertIn("CURRENT SERVER SCRIPT", out["dialog_context"])
		self.assertIn(CONTRACT_MARKER, out["dialog_context"])
		# The script block must come before the contract so the contract is
		# the last instruction the model reads.
		self.assertLess(
			out["dialog_context"].index("CURRENT SERVER SCRIPT"),
			out["dialog_context"].index(CONTRACT_MARKER),
		)
