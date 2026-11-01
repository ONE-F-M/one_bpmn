# Copyright (c) 2026, one-fm and contributors
"""Docu has one retry rule, and its Schema Writer is bounded, guarded, shown examples and carries the form design rules."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_settings_are_bounded as fix

OLD_RETRY = "repeat write_schema then review_schema at most 2 more times"
OLD_LEAD = "You run ONE turn of the Docu DocType-builder assistant by calling tools. " + OLD_RETRY
RULES = "\n\nPIPELINE RULES: (4) call write_schema, then review_schema; at most three times."


class TestDocuSettingsAreBounded(FrappeTestCase):
	def setUp(self):
		self.agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": fix.AGENT}, "name")
		self.writer = frappe.db.get_value("AI Agent Configuration", {"agent_id": fix.WRITER}, "name")
		if not self.agent or not self.writer:
			self.skipTest("Docu or its Schema Writer is not on this site")
		if not frappe.db.exists("AI Skill", fix.DESIGN_SKILL):
			self.skipTest("the form design rules skill is not on this site")
		frappe.db.set_value("AI Agent Configuration", self.agent, "system_prompt", OLD_LEAD + RULES)
		frappe.db.set_value("AI Agent Configuration", self.writer, {"max_tokens": 0, "top_p": 0})

	def _writer(self):
		return frappe.get_doc("AI Agent Configuration", self.writer)

	def test_the_agent_prompt_keeps_one_retry_rule(self):
		fix.execute()

		prompt = frappe.db.get_value("AI Agent Configuration", self.agent, "system_prompt")
		self.assertNotIn(OLD_RETRY, prompt)
		self.assertEqual(prompt.count("at most three times"), 1)
		self.assertTrue(prompt.startswith("PIPELINE RULES"))

	def test_the_writer_is_bounded_guarded_and_shown_two_examples(self):
		fix.execute()

		writer = self._writer()
		self.assertEqual(writer.max_tokens, 16384)
		self.assertEqual(writer.top_p, 1)
		self.assertEqual([r.enabled for r in writer.guardrails if r.category == "Safety"], [1])
		self.assertEqual({r.input for r in writer.examples}, {e["input"] for e in fix.EXAMPLES})

	def test_the_writer_carries_the_design_rules_and_does_not_load_them(self):
		fix.execute()

		writer = self._writer()
		self.assertNotIn(fix.ALWAYS_LOAD, writer.system_prompt)
		self.assertIn(fix.RULES_HEADING, writer.system_prompt)
		self.assertNotIn(fix.DESIGN_SKILL, {r.skill for r in writer.enabled_skills})

	def test_running_it_twice_changes_nothing_more(self):
		fix.execute()
		first = self._writer()
		prompt, examples, guardrails = first.system_prompt, len(first.examples), len(first.guardrails)

		fix.execute()

		second = self._writer()
		self.assertEqual(second.system_prompt, prompt)
		self.assertEqual(len(second.examples), examples)
		self.assertEqual(len(second.guardrails), guardrails)
