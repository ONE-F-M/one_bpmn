# Copyright (c) 2026, one-fm and contributors
"""The coding agents get the turn-budget rules once, after the rules already in their prompt."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import coding_agents_work_within_their_turns as patch


class TestCodingAgentsWorkWithinTheirTurnsPatch(FrappeTestCase):
	def setUp(self):
		self.present = [a for a in patch.AGENTS if frappe.db.exists("AI Agent Configuration", a)]
		if not self.present:
			self.skipTest("none of the coding agents is on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self, name):
		return frappe.db.get_value("AI Agent Configuration", name, "system_prompt")

	def test_the_rules_land_once_after_the_existing_prompt(self):
		for name in self.present:
			frappe.db.set_value("AI Agent Configuration", name, "system_prompt", "Do the job.\n\nBatched tools:\n- a rule", update_modified=False)
		patch.execute()
		patch.execute()
		for name in self.present:
			prompt = self._prompt(name)
			self.assertTrue(prompt.startswith("Do the job.\n\nBatched tools:\n- a rule"), name)
			self.assertEqual(prompt.count(patch.marker()), 1, name)
			self.assertIn("run budget line", prompt)
			self.assertIn("list every fix it shows", prompt)

	def test_a_reworded_block_is_replaced_not_stacked(self):
		name = self.present[0]
		frappe.db.set_value(
			"AI Agent Configuration", name, "system_prompt",
			"Do the job.\n\n" + patch.marker() + "\n- an old rule nobody wants\n", update_modified=False,
		)
		patch.execute()
		prompt = self._prompt(name)
		self.assertNotIn("an old rule nobody wants", prompt)
		self.assertTrue(prompt.startswith("Do the job."))

	def test_the_tool_call_cap_is_left_as_it_is(self):
		name = self.present[0]
		frappe.db.set_value("AI Agent Configuration", name, "max_tool_calls", 25, update_modified=False)
		patch.execute()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", name, "max_tool_calls"), 25)

	def test_an_agent_that_is_not_on_the_site_is_skipped(self):
		missing = [a for a in patch.AGENTS if a not in self.present]
		patch.execute()
		for name in missing:
			self.assertFalse(frappe.db.exists("AI Agent Configuration", name))
