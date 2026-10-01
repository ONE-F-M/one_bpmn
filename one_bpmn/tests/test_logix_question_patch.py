# Copyright (c) 2026, one-fm and contributors

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import logix_answers_questions_and_always_offers_options as patch

WRITER = "You are Logix.\n\nOUTPUT:\n- The whole script in one python code block.\n\nQUESTIONS:\nAnswer in words."
CLARIFIER = "Rules:\n- Give 2-4 plain-English options to choose from whenever possible."
SKILL_BODY = "# Changing an existing script\n\nWork from the current code.\n"


class TestLogixQuestionPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for agent_id, prompt in (("logix_script_writer", WRITER), ("logix_clarifier", CLARIFIER)):
			name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id})
			if name:
				frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt)
				continue
			frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": f"ZZ {agent_id}",
					"agent_id": agent_id,
					"agent_type": "Background",
					"agent_framework": "Direct API",
					"system_prompt": prompt,
				}
			).insert(ignore_permissions=True)
		if frappe.db.exists("AI Skill", patch.SKILL):
			frappe.db.set_value("AI Skill", patch.SKILL, "body", SKILL_BODY)
		else:
			frappe.get_doc({"doctype": "AI Skill", "name": patch.SKILL, "body": SKILL_BODY}).db_insert()

	def _prompt(self, agent_id):
		return frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "system_prompt")

	def test_the_modify_skill_lets_a_question_go_unrewritten_once(self):
		patch.execute()
		patch.execute()
		body = frappe.db.get_value("AI Skill", patch.SKILL, "body")
		self.assertEqual(body.count(patch.SKILL_RULE), 1)
		self.assertLess(body.index(patch.SKILL_RULE), body.index("Work from the current code."))

	def test_the_writer_only_owes_a_script_when_a_change_was_asked_for(self):
		patch.execute()
		self.assertIn("OUTPUT (when the person asked for a change", self._prompt("logix_script_writer"))

	def test_the_clarifier_never_offers_an_empty_list(self):
		patch.execute()
		prompt = self._prompt("logix_clarifier")
		self.assertIn("never an empty list", prompt)
		self.assertNotIn("whenever possible", prompt)
