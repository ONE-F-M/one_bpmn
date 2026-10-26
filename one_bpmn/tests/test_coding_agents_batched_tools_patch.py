# Copyright (c) 2026, one-fm and contributors
"""The coding agents get the batched-tool and evidence rules once, and a tool-call cap of 40."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import coding_agents_use_batched_tools_and_evidence as patch


class TestCodingAgentsBatchedToolsPatch(FrappeTestCase):
	def setUp(self):
		self.present = [a for a in patch.AGENTS if frappe.db.exists("AI Agent Configuration", a)]
		if not self.present:
			self.skipTest("none of the coding agents is on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _config(self, name):
		return frappe.db.get_value("AI Agent Configuration", name, ["system_prompt", "max_tool_calls"], as_dict=True)

	def test_the_rules_land_once_after_the_existing_prompt_and_the_cap_is_raised(self):
		for name in self.present:
			frappe.db.set_value(
				"AI Agent Configuration", name, {"system_prompt": "Do the job.", "max_tool_calls": 10, "max_retries": 1}, update_modified=False
			)
		patch.execute()
		patch.execute()
		for name in self.present:
			config = self._config(name)
			self.assertTrue(config.system_prompt.startswith("Do the job."), name)
			self.assertEqual(config.system_prompt.count(patch.marker()), 1, name)
			self.assertIn("read_files", config.system_prompt)
			self.assertIn("submit_evidence", config.system_prompt)
			self.assertIn("Two edit_file calls in a row", config.system_prompt)
			self.assertEqual(config.max_tool_calls, patch.MAX_TOOL_CALLS, name)
			self.assertEqual(frappe.db.get_value("AI Agent Configuration", name, "max_retries"), patch.MODEL_RETRIES, name)

	def test_a_higher_cap_is_kept(self):
		name = self.present[0]
		frappe.db.set_value("AI Agent Configuration", name, "max_tool_calls", 60, update_modified=False)
		patch.execute()
		self.assertEqual(self._config(name).max_tool_calls, 60)

	def test_a_reworded_block_is_replaced_not_stacked(self):
		name = self.present[0]
		frappe.db.set_value(
			"AI Agent Configuration", name, "system_prompt",
			"Do the job.\n\n" + patch.marker() + "\n- an old rule nobody wants\n", update_modified=False,
		)
		patch.execute()
		prompt = self._config(name).system_prompt
		self.assertNotIn("an old rule nobody wants", prompt)
		self.assertTrue(prompt.startswith("Do the job."))

	def test_an_agent_that_is_not_on_the_site_is_skipped(self):
		missing = [a for a in patch.AGENTS if a not in self.present]
		patch.execute()
		for name in missing:
			self.assertFalse(frappe.db.exists("AI Agent Configuration", name))
