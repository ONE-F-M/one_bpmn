# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Logix's fixed turn rules move into its system prompt and leave the user message."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.context_assembler import build_dynamic_preamble, drop_duplicated_instructions
from one_bpmn.one_bpmn.patches.v1_0 import logix_turn_rules_in_system_prompt as fix

PROMPT = "You run ONE turn of the Logix script-writing assistant by calling tools, one at a time."


def _logix(system_prompt: str):
	if not frappe.db.exists("AI Agent Configuration", fix.AGENT):
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": fix.AGENT,
				"agent_id": "logix_agent_rules_test",
				"agent_type": "Chat",
				"agent_framework": "Direct API",
				"chat_mode_label": "Logix rules test",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("AI Agent Configuration", fix.AGENT, "system_prompt", system_prompt)


def _system_prompt() -> str:
	return frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt")


class TestLogixTurnRules(FrappeTestCase):
	def test_the_rules_are_appended_once(self):
		_logix(PROMPT)
		fix.execute()
		fix.execute()
		self.assertEqual(_system_prompt(), f"{PROMPT}\n\n{fix.TURN_RULES}")

	def test_a_configuration_without_its_own_prompt_is_left_to_the_map(self):
		_logix("")
		fix.execute()
		self.assertFalse(_system_prompt())

	def test_the_user_message_keeps_memory_and_the_words_and_drops_the_rules(self):
		_logix(PROMPT)
		fix.execute()
		user = build_dynamic_preamble(
			memory_block="Recalled: the person prefers frappe.qb.",
			instructions=fix.TURN_RULES,
			user_prompt="Make this script skip cancelled orders.",
		)
		self.assertIn(fix.TURN_RULES, user)
		sent = drop_duplicated_instructions(_system_prompt(), user)
		self.assertNotIn("HARD PIPELINE RULES", sent)
		self.assertIn("Recalled: the person prefers frappe.qb.", sent)
		self.assertIn("Make this script skip cancelled orders.", sent)
