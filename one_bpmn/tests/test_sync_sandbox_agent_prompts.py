# Copyright (c) 2026, one-fm and contributors
"""The patch that carries what an export cannot: the three sandbox agents'
prompts and the Mobile App Agent's base branch."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import sync_sandbox_agent_prompts as patch


class TestSyncSandboxAgentPrompts(FrappeTestCase):
	def setUp(self):
		for agent in patch._AGENT_SEEDS:
			if not frappe.db.exists("AI Agent Configuration", agent):
				self.skipTest(f"{agent} is not on this site")

	def test_prompts_are_reset_to_the_seed_and_mobile_bases_on_version_15(self):
		for agent in patch._AGENT_SEEDS:
			frappe.db.set_value("AI Agent Configuration", agent, "system_prompt", "stale prompt calling dispatch_to_sandbox")
		mobile = frappe.get_doc("AI Agent Configuration", "Mobile App Agent")
		patch._set_constant(mobile, "base_branch", "staging")
		mobile.save(ignore_permissions=True)

		patch.execute()

		for agent, module in patch._AGENT_SEEDS.items():
			self.assertEqual(
				frappe.db.get_value("AI Agent Configuration", agent, "system_prompt"),
				frappe.get_attr(module + "._SYSTEM_PROMPT"),
				agent,
			)
		constants = {r.constant_name: r.constant_value for r in frappe.get_doc("AI Agent Configuration", "Mobile App Agent").constants}
		self.assertEqual(constants["base_branch"], "version-15")

	def test_running_twice_changes_nothing_more(self):
		patch.execute()
		before = {a: frappe.db.get_value("AI Agent Configuration", a, ["system_prompt", "modified"], as_dict=True) for a in patch._AGENT_SEEDS}
		patch.execute()
		for a in patch._AGENT_SEEDS:
			self.assertEqual(frappe.db.get_value("AI Agent Configuration", a, "system_prompt"), before[a].system_prompt)

	def test_a_missing_base_branch_row_is_added_not_assumed(self):
		mobile = frappe.get_doc("AI Agent Configuration", "Mobile App Agent")
		mobile.constants = [r for r in mobile.constants if r.constant_name != "base_branch"]
		mobile.save(ignore_permissions=True)
		patch.execute()
		constants = {r.constant_name: r.constant_value for r in frappe.get_doc("AI Agent Configuration", "Mobile App Agent").constants}
		self.assertEqual(constants["base_branch"], "version-15")
