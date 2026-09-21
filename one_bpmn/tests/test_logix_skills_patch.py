# Copyright (c) 2026, one-fm and contributors
"""Seeding Logix's skills.

A seed patch runs on every migrate, so what matters is that a second run changes
nothing, that a writer prompt someone has since edited is not overwritten, and
that a site without the Logix stage configurations is left alone. No model call
is made: the description review is skipped under test.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.skill_tools import _skill_names_cache_key, _skills_cache_key
from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_skills as seed

WRITERS_PRESENT = all(
	frappe.db.exists("AI Agent Configuration", {"agent_id": agent_id}) for agent_id in seed.WRITER_AGENT_IDS
)


class TestLogixSkillsSeed(FrappeTestCase):
	def _writer(self, agent_id: str):
		return frappe.get_doc(
			"AI Agent Configuration", frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		)

	def test_a_site_without_the_writers_only_gets_the_skills(self):
		with mock_patch.object(seed, "WRITER_AGENT_IDS", ("no_such_writer",)), mock_patch.object(
			seed, "MAIN_AGENT_ID", "no_such_agent"
		):
			seed.execute()
		for skill in seed.SKILLS:
			self.assertEqual(frappe.db.get_value("AI Skill", skill["skill_name"], "status"), "Active")

	def test_seeding_twice_leaves_one_row_per_skill_and_keeps_an_edited_prompt(self):
		if not WRITERS_PRESENT:
			self.skipTest("Logix writer configurations are not on this site")

		seed.execute()
		names = {s["skill_name"] for s in seed.SKILLS}
		for agent_id in seed.WRITER_AGENT_IDS:
			doc = self._writer(agent_id)
			self.assertEqual({row.skill for row in doc.enabled_skills}, names)
			self.assertEqual(len(doc.enabled_skills), len(names))
			self.assertIn(seed.PROMPT_MARKER, doc.system_prompt)
			self.assertNotIn("CONTRACT A", doc.system_prompt)

		edited = self._writer(seed.WRITER_AGENT_IDS[0])
		edited.system_prompt = "Edited by a person. Still says load_skill."
		edited.save(ignore_permissions=True)

		seed.execute()

		self.assertEqual(self._writer(seed.WRITER_AGENT_IDS[0]).system_prompt, edited.system_prompt)
		for agent_id in seed.WRITER_AGENT_IDS:
			self.assertEqual(len(self._writer(agent_id).enabled_skills), len(names))

	def test_only_the_dead_sub_prompts_leave_the_main_configuration(self):
		main = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.MAIN_AGENT_ID}, "name")
		if not main:
			self.skipTest("Logix is not on this site")
		seed.execute()
		ids = {row.sub_agent_id for row in frappe.get_doc("AI Agent Configuration", main).sub_prompts}
		self.assertFalse(ids & set(seed.DEAD_SUB_PROMPTS))
		self.assertTrue({"script_reviewer", "test_writer"} <= ids)
		prompt = frappe.db.get_value("AI Agent Configuration", main, "system_prompt")
		self.assertEqual(prompt.count(seed.ROUTING_MARKER), 1)
		seed.execute()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", main, "system_prompt"), prompt)

	def test_a_loaded_skill_is_scoped_to_its_agent(self):
		self.assertNotEqual(_skills_cache_key("c1", "Logix – Script Writer"), _skills_cache_key("c1", "Logix"))
		self.assertNotEqual(_skill_names_cache_key("c1", "a"), _skill_names_cache_key("c1", "b"))
