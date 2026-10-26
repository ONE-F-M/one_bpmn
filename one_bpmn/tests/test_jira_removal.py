# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Jira is gone from Processa Settings and from the BA agents' prompts."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import remove_jira_from_agent_prompts as patch

JIRA_BLOCK = patch.EDITS["BA Agent"][1][0]


class TestJiraRemoval(FrappeTestCase):
	def test_processa_settings_has_no_jira_fields(self):
		fields = [f.fieldname for f in frappe.get_meta("Processa Settings").fields]
		self.assertFalse([f for f in fields if f.startswith("jira")])

	def test_the_patch_strips_the_jira_block_and_clears_the_cached_config(self):
		if not frappe.db.exists("AI Agent Configuration", "BA Agent"):
			self.skipTest("no BA Agent configuration on this site")
		agent_id = frappe.db.get_value("AI Agent Configuration", "BA Agent", "agent_id")
		frappe.db.set_value("AI Agent Configuration", "BA Agent", "system_prompt", f"Approve the stories.{JIRA_BLOCK}\n\nEnd.")
		frappe.cache.set_value(f"agent_config:{agent_id}", {"system_prompt": "stale"})

		patch.execute()

		prompt = frappe.db.get_value("AI Agent Configuration", "BA Agent", "system_prompt")
		self.assertEqual(prompt, "Approve the stories.\n\nEnd.")
		self.assertIsNone(frappe.cache.get_value(f"agent_config:{agent_id}"))
