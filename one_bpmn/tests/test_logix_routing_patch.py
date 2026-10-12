# Copyright (c) 2026, one-fm and contributors

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import logix_routes_questions_and_vague_requests as routing


class TestLogixRoutingPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for agent_id in routing.RULES:
			name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id})
			if name:
				frappe.db.set_value("AI Agent Configuration", name, "system_prompt", "Base prompt.")
				continue
			frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": f"ZZ {agent_id}",
					"agent_id": agent_id,
					"agent_type": "Background",
					"agent_framework": "Direct API",
					"system_prompt": "Base prompt.",
				}
			).insert(ignore_permissions=True)

	def _prompt(self, agent_id):
		return frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "system_prompt")

	def test_each_rule_is_appended_once(self):
		routing.execute()
		routing.execute()
		for agent_id, rule in routing.RULES.items():
			prompt = self._prompt(agent_id)
			self.assertTrue(prompt.startswith("Base prompt."), agent_id)
			self.assertEqual(prompt.count(rule.strip()), 1, agent_id)

	def test_the_classifier_sends_a_pointer_at_nothing_to_disambiguate(self):
		routing.execute()
		prompt = self._prompt("logix_intent_classifier")
		self.assertIn("adapt this logic", prompt)
		self.assertIn("is DISAMBIGUATE", prompt)


class TestTurnSurvivesCacheWipe(FrappeTestCase):
	def test_a_running_turn_outlives_a_global_cache_clear(self):
		set_turn("zz-turn-conv", {"element_name": "Update Employee Checkin"})
		self.addCleanup(frappe.cache.delete_value, "ait_turn:zz-turn-conv")
		frappe.clear_cache()
		self.assertEqual(get_turn("zz-turn-conv"), {"element_name": "Update Employee Checkin"})
