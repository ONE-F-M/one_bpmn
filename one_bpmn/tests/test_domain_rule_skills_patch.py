# Copyright (c) 2026, one-fm and contributors
"""Moving the safety list and the form design rules into skills.

Pins that a second run changes nothing, that a prompt someone has since edited
is not overwritten (the old block is the anchor, and an edited prompt no longer
carries it), and that the skills reach the writer records. No model call is made
under test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import move_domain_rules_into_skills as seed

WRITERS = {
	agent_id: frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
	for agent_id in seed.LOGIX_WRITER_AGENT_IDS + (seed.DOCU_WRITER_AGENT_ID,)
}


class TestDomainRuleSkills(FrappeTestCase):
	def _sub_prompt(self, agent_id: str, sub_agent_id: str) -> str:
		parent = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		return frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": parent, "sub_agent_id": sub_agent_id}, "prompt_text"
		) or ""

	def test_skills_exist_and_reach_the_writers(self):
		if not all(WRITERS.values()):
			self.skipTest("Logix or Docu writer records are not on this site")
		seed.execute()
		for skill in seed.SKILLS:
			self.assertEqual(frappe.db.get_value("AI Skill", skill["skill_name"], "status"), "Active")
		for agent_id in seed.LOGIX_WRITER_AGENT_IDS:
			doc = frappe.get_doc("AI Agent Configuration", WRITERS[agent_id])
			self.assertIn(seed.SAFETY_SKILL, {r.skill for r in doc.enabled_skills})
			self.assertNotIn(seed.LOGIX_WRITER_OLD_MARKER, doc.system_prompt)
			self.assertIn(seed.SAFETY_SKILL, doc.system_prompt)
		docu = frappe.get_doc("AI Agent Configuration", WRITERS[seed.DOCU_WRITER_AGENT_ID])
		self.assertIn(seed.DESIGN_SKILL, {r.skill for r in docu.enabled_skills})
		self.assertNotIn(seed.DOCU_WRITER_OLD_MARKER, docu.system_prompt)
		self.assertIn(seed.DESIGN_SKILL, docu.system_prompt)
		self.assertNotIn(seed.LOGIX_REVIEWER_OLD_MARKER, self._sub_prompt(seed.LOGIX_AGENT_ID, "script_reviewer"))
		self.assertNotIn(seed.DOCU_REVIEWER_OLD_MARKER, self._sub_prompt(seed.DOCU_AGENT_ID, "schema_reviewer"))

	def test_second_run_keeps_an_edited_prompt_and_adds_no_rows(self):
		if not all(WRITERS.values()):
			self.skipTest("Logix or Docu writer records are not on this site")
		seed.execute()
		doc = frappe.get_doc("AI Agent Configuration", WRITERS[seed.DOCU_WRITER_AGENT_ID])
		rows = len(doc.enabled_skills)
		before = doc.system_prompt
		doc.system_prompt = "Edited by a person."
		doc.save(ignore_permissions=True)
		try:
			seed.execute()
			doc.reload()
			self.assertEqual(doc.system_prompt, "Edited by a person.")
			self.assertEqual(len(doc.enabled_skills), rows)
		finally:
			doc.reload()
			doc.system_prompt = before
			doc.save(ignore_permissions=True)
