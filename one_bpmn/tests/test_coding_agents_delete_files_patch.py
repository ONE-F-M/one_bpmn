# Copyright (c) 2026, one-fm and contributors
"""The coding agents are told to delete a file they no longer need, once, beside the rules they already have."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import coding_agents_delete_files_they_no_longer_need as patch


class TestCodingAgentsDeleteFilesPatch(FrappeTestCase):
	def setUp(self):
		self.present = [a for a in patch.AGENTS if frappe.db.exists("AI Agent Configuration", a)]
		if not self.present:
			self.skipTest("none of the coding agents is on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self, agent):
		return frappe.db.get_value("AI Agent Configuration", agent, "system_prompt")

	def test_the_rule_lands_once_after_the_existing_prompt(self):
		for agent in self.present:
			frappe.db.set_value("AI Agent Configuration", agent, "system_prompt", "Do the job.\n\nEarlier rules:\n- one", update_modified=False)
		patch.execute()
		patch.execute()
		for agent in self.present:
			prompt = self._prompt(agent)
			self.assertTrue(prompt.startswith("Do the job.\n\nEarlier rules:\n- one"), agent)
			self.assertEqual(prompt.count(patch.marker()), 1, agent)
			self.assertIn("Never empty it with write_file", prompt)

	def test_a_reworded_block_is_replaced_not_stacked(self):
		agent = self.present[0]
		frappe.db.set_value(
			"AI Agent Configuration", agent, "system_prompt",
			"Do the job.\n\n" + patch.marker() + "\n- an old rule nobody wants\n", update_modified=False,
		)
		patch.execute()
		self.assertNotIn("an old rule nobody wants", self._prompt(agent))

	def test_every_agent_it_names_has_the_delete_tool_in_its_map(self):
		for agent in self.present:
			xml = frappe.db.get_value("BPMN Process Model", {"title": agent}, "bpmn_xml") or ""
			if not xml:
				continue
			self.assertIn("Sandbox Tool: Delete File", xml, agent)
