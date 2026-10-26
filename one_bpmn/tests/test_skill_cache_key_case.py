# Copyright (c) 2026, one-fm and contributors
"""A skill preloaded under the record's name is read back under the map's spelling of it."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.api.skill_tools import _skill_names_cache_key, _skills_cache_key

AGENT = "_Test Skill Key Agent"


class TestSkillCacheKeyCase(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", AGENT):
			make_agent_configuration(
				agent_name=AGENT, agent_id="_test_skill_key_agent", chat_mode_label=AGENT
			)

	def test_the_map_spelling_and_the_record_name_share_one_key(self):
		self.assertEqual(_skills_cache_key("c1", AGENT.lower()), _skills_cache_key("c1", AGENT))
		self.assertEqual(_skill_names_cache_key("c1", AGENT.upper()), _skill_names_cache_key("c1", AGENT))
		self.assertIn(f"_{AGENT}", _skills_cache_key("c1", AGENT.lower()))

	def test_a_name_with_no_record_keeps_its_own_key(self):
		self.assertNotEqual(
			_skills_cache_key("c1", "No Such Agent"), _skills_cache_key("c1", "Another Missing")
		)
		self.assertEqual(_skills_cache_key("c1", "No Such Agent"), "active_skills_c1_No Such Agent")
