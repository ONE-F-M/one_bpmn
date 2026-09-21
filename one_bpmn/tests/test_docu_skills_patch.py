# Copyright (c) 2026, one-fm and contributors
"""Seeding Docu's skills.

Pins the same three things as the Logix seed: a second run changes nothing, a
writer prompt someone has since edited is not overwritten, and a site without
Docu only gets the skills. No model call is made under test.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_skills as seed

DOCU = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")


class TestDocuSkillsSeed(FrappeTestCase):
	def _sub_prompt(self, sub_agent_id: str) -> str:
		return frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": DOCU, "sub_agent_id": sub_agent_id}, "prompt_text"
		)

	def test_a_site_without_docu_only_gets_the_skills(self):
		with mock_patch.object(seed, "AGENT_ID", "no_such_agent"):
			seed.execute()
		for skill in seed.SKILLS:
			self.assertEqual(frappe.db.get_value("AI Skill", skill["skill_name"], "status"), "Active")

	def test_seeding_twice_leaves_one_row_per_skill_and_keeps_an_edited_prompt(self):
		if not DOCU:
			self.skipTest("Docu is not on this site")

		seed.execute()
		names = {s["skill_name"] for s in seed.SKILLS}
		doc = frappe.get_doc("AI Agent Configuration", DOCU)
		self.assertFalse({row.skill for row in doc.enabled_skills} & names, "skills belong to the writer stage")
		writer = frappe.get_doc(
			"AI Agent Configuration",
			frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.WRITER_AGENT_ID}, "name"),
		)
		self.assertEqual({row.skill for row in writer.enabled_skills}, names)
		self.assertEqual(len(writer.enabled_skills), len(names))
		self.assertEqual(writer.agent_type, "Background")
		self.assertIsNone(self._sub_prompt("schema_writer"), "the writer's prompt lives on its own record")
		self.assertIn("load_skill", writer.system_prompt)
		self.assertNotIn(seed.REDIRECT_OLD, self._sub_prompt("redirect"))

		writer.system_prompt = "Edited by a person."
		writer.save(ignore_permissions=True)

		seed.execute()

		writer.reload()
		self.assertEqual(writer.system_prompt, "Edited by a person.")
		self.assertEqual(
			frappe.db.count("AI Agent Configuration", {"agent_id": seed.WRITER_AGENT_ID}), 1, "one writer stage"
		)
		self.assertEqual(
			frappe.db.count("AI Agent Enabled Skill", {"parenttype": "AI Agent Configuration", "parent": writer.name}),
			len(names),
		)
