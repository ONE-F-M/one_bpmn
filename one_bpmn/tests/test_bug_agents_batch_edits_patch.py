# Copyright (c) 2026, one-fm and contributors
"""The Bug Programmer gets the batching rule and the Bug Planner and Reviewer the reading rule, once, beside the rules they already have."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import bug_agents_batch_edits_and_read_less as patch


class TestBugAgentsBatchEditsPatch(FrappeTestCase):
	def setUp(self):
		self.present = [a for a in patch.RULES if frappe.db.exists("AI Agent Configuration", a)]
		if not self.present:
			self.skipTest("none of the bug agents is on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self, agent):
		return frappe.db.get_value("AI Agent Configuration", agent, "system_prompt")

	def test_each_agent_gets_its_block_once_and_keeps_its_other_blocks(self):
		for agent in self.present:
			frappe.db.set_value("AI Agent Configuration", agent, "system_prompt", "Do the job.\n\nWorking on a bug:\n- a rule", update_modified=False)
		patch.execute()
		patch.execute()
		for agent in self.present:
			prompt = self._prompt(agent)
			self.assertTrue(prompt.startswith("Do the job.\n\nWorking on a bug:\n- a rule"), agent)
			self.assertEqual(prompt.count(patch.marker(agent)), 1, agent)

	def test_only_the_programmer_is_told_about_apply_edits(self):
		patch.execute()
		if "Bug Programmer" in self.present:
			self.assertIn("apply_edits", self._prompt("Bug Programmer"))
		for agent in ("Bug Planner", "Bug Reviewer"):
			if agent in self.present:
				self.assertNotIn("apply_edits", self._prompt(agent))
				self.assertIn("read_files", self._prompt(agent))

	def test_a_reworded_block_is_replaced_not_stacked(self):
		agent = self.present[0]
		frappe.db.set_value(
			"AI Agent Configuration", agent, "system_prompt",
			"Do the job.\n\n" + patch.marker(agent) + "\n- an old rule nobody wants\n", update_modified=False,
		)
		patch.execute()
		self.assertNotIn("an old rule nobody wants", self._prompt(agent))
