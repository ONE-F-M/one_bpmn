# Copyright (c) 2026, one-fm and contributors
"""Seeding LuCrusher's phase skills.

Phases 4 to 6 leave the system prompt for skills, phases 1 to 3 stay, a second run changes
nothing, and a prompt someone has since edited is not overwritten. No model call is made.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.context_assembler import drop_duplicated_instructions
from one_bpmn.one_bpmn.patches.v1_0 import seed_lucrusher_skills as seed

LUCRUSHER = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
SKILL_NAMES = {s["skill_name"] for s in seed.SKILLS}


class TestLucrusherSkillsSeed(FrappeTestCase):
	def test_a_site_without_lucrusher_only_gets_the_skills(self):
		with mock_patch.object(seed, "AGENT_ID", "no_such_agent"):
			seed.execute()
		for name in SKILL_NAMES:
			self.assertEqual(frappe.db.get_value("AI Skill", name, "status"), "Active")

	def test_phase_rules_move_to_skills_and_phases_one_to_three_stay(self):
		self.assertNotIn("R1:", seed.SYSTEM_PROMPT)
		self.assertNotIn("CODE REMOVAL", seed.SYSTEM_PROMPT)
		self.assertNotIn("ANTI-LINTING", seed.SYSTEM_PROMPT)
		for tool in (
			"search_processes_on_production",
			"fetch_lucidchart_document",
			"scan_codebase_for_process",
		):
			self.assertIn(tool, seed.SYSTEM_PROMPT)
		for name in SKILL_NAMES:
			self.assertIn(name, seed.SYSTEM_PROMPT)

	def test_the_map_user_prompt_still_loses_its_copy_of_the_turn_block(self):
		user_prompt = f"Current migration context: none\n\n{seed.TURN_BLOCK}\n\nUser message: Visa"
		self.assertNotIn(seed.TURN_BLOCK, drop_duplicated_instructions(seed.SYSTEM_PROMPT, user_prompt))

	def test_seeding_twice_enables_each_skill_once_and_keeps_an_edited_prompt(self):
		if not LUCRUSHER:
			self.skipTest("LuCrusher is not on this site")

		frappe.db.set_value(
			"AI Agent Configuration", LUCRUSHER, "system_prompt", "R1: One goal = one process."
		)
		seed.execute()
		seed.execute()

		doc = frappe.get_doc("AI Agent Configuration", LUCRUSHER)
		self.assertEqual(doc.system_prompt, seed.SYSTEM_PROMPT)
		enabled = [row.skill for row in doc.enabled_skills]
		self.assertTrue(SKILL_NAMES <= set(enabled))
		self.assertEqual(len(enabled), len(set(enabled)), "no duplicate rows")

		frappe.db.set_value(
			"AI Agent Configuration", LUCRUSHER, "system_prompt", "Edited by a person. load_skill"
		)
		seed.execute()
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", LUCRUSHER, "system_prompt"),
			"Edited by a person. load_skill",
		)
