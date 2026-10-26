# Copyright (c) 2026, one-fm and contributors
"""The Frontend and Mobile App agents each get their own search and read rules once, as the tail of the prompt."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import frontend_and_mobile_agents_search_and_read_less as patch


class TestFrontendAndMobileSearchPatch(FrappeTestCase):
	def setUp(self):
		self.present = [a for a in patch.RULES if frappe.db.exists("AI Agent Configuration", a)]
		if not self.present:
			self.skipTest("neither the Frontend nor the Mobile App agent is on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self, agent):
		return frappe.db.get_value("AI Agent Configuration", agent, "system_prompt")

	def test_each_agent_gets_its_own_rules_once_after_its_existing_prompt(self):
		for agent in self.present:
			frappe.db.set_value("AI Agent Configuration", agent, "system_prompt", "Do the job.\n\nEarlier rules:\n- one", update_modified=False)
		patch.execute()
		patch.execute()
		for agent in self.present:
			prompt = self._prompt(agent)
			self.assertTrue(prompt.startswith("Do the job.\n\nEarlier rules:\n- one"), agent)
			self.assertEqual(prompt.count(patch.marker(agent)), 1, agent)
			for other in patch.RULES:
				if other != agent:
					self.assertNotIn(patch.marker(other), prompt, agent)

	def test_the_front_end_rules_name_search_frontend_and_the_mobile_rules_name_search_repo(self):
		if "Frontend Agent" in self.present:
			patch.execute()
			self.assertIn("search_frontend", self._prompt("Frontend Agent"))
		if "Mobile App Agent" in self.present:
			patch.execute()
			self.assertIn("search_repo", self._prompt("Mobile App Agent"))

	def test_a_reworded_block_is_replaced_not_stacked(self):
		agent = self.present[0]
		frappe.db.set_value(
			"AI Agent Configuration", agent, "system_prompt",
			"Do the job.\n\n" + patch.marker(agent) + "\n- an old rule nobody wants\n", update_modified=False,
		)
		patch.execute()
		prompt = self._prompt(agent)
		self.assertNotIn("an old rule nobody wants", prompt)
		self.assertTrue(prompt.startswith("Do the job."))
