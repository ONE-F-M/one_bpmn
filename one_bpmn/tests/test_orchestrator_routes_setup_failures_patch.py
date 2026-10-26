# Copyright (c) 2026, one-fm and contributors
"""The Orchestrator gets the Bug Agent or Dev Agent routing rule once, after the rules already in its prompt."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_routes_setup_failures_to_the_dev_agent as patch


class TestOrchestratorRoutesSetupFailuresPatch(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", patch.AGENT):
			self.skipTest("the Orchestrator Agent is not on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self):
		return frappe.db.get_value("AI Agent Configuration", patch.AGENT, "system_prompt")

	def test_the_rule_lands_once_after_the_existing_prompt(self):
		frappe.db.set_value("AI Agent Configuration", patch.AGENT, "system_prompt", "Orchestrate.\n\nEarlier rules:\n- one", update_modified=False)
		patch.execute()
		patch.execute()
		prompt = self._prompt()
		self.assertTrue(prompt.startswith("Orchestrate.\n\nEarlier rules:\n- one"))
		self.assertEqual(prompt.count(patch.marker()), 1)
		self.assertIn("installing, migrating", prompt)

	def test_a_reworded_block_is_replaced_not_stacked(self):
		frappe.db.set_value(
			"AI Agent Configuration", patch.AGENT, "system_prompt",
			"Orchestrate.\n\n" + patch.marker() + "\n- an old rule nobody wants\n", update_modified=False,
		)
		patch.execute()
		prompt = self._prompt()
		self.assertNotIn("an old rule nobody wants", prompt)
		self.assertTrue(prompt.startswith("Orchestrate."))
