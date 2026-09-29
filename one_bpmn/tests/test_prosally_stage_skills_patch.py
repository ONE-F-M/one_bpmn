# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's diagram stages append their skills instead of asking a tool-less model to load them.

The inserted script line is run under split globals and locals, as the shape-tool exec runs it.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import prosally_stage_skills as patch
from one_bpmn.one_bpmn.patches.v1_0 import seed_prosally_and_frontend_skills as earlier

PROSALLY = frappe.db.get_value("AI Agent Configuration", {"agent_id": patch.AGENT_ID}, "name")

GENERATOR = (
	"You are a BPMN process modeller.\n\n" + earlier.GEN_STEP0_NEW + "=== IR SCHEMA ===\nschema\n\n"
	"=== NODE TYPES: WHO DOES THE WORK? ===\nnode types\n\n"
	"=== FLOW RULES ===\nflow rules\n\n"
	"=== OUTPUT ===\nOutput ONLY JSON." + earlier.REWORK_RULE_NEW + "\n=== TOPOLOGY ===\ntopology\n"
)


class TestProsAllyStageSkills(FrappeTestCase):
	def test_the_generator_prompt_loses_what_the_skills_carry(self):
		text = patch.trimmed_prompt(GENERATOR)
		for gone in ("load_skill", "NODE TYPES", "FLOW RULES", "STEP 0"):
			self.assertNotIn(gone, text)
		for kept in ("=== IR SCHEMA ===", "=== OUTPUT ===", "=== TOPOLOGY ===", "Output ONLY JSON."):
			self.assertIn(kept, text)
		self.assertEqual(patch.trimmed_prompt(text), text)

	def test_the_modifier_points_at_the_appended_lane_skill_and_keeps_its_assign_rule(self):
		text = patch.trimmed_prompt("=== SWIM LANES ===\n" + earlier.MOD_NEW)
		self.assertNotIn("load the bpmn-modelling-rules-and-ir-schema skill", text)
		self.assertIn(patch.MOD_LANE_POINTER_NEW, text)
		self.assertIn("  Assign: userTask", text)

	def test_the_script_line_puts_both_skill_bodies_in_the_system_prompt(self):
		_upsert_both_skills()
		scope = {"_system": "Stage prompt."}
		exec(patch.SKILL_LINE, {"frappe": frappe}, scope)
		system = scope["_system"]
		self.assertTrue(system.startswith("Stage prompt."))
		self.assertIn("## Skill: bpmn-modelling-rules-and-ir-schema", system)
		self.assertIn("## Lane fidelity", system)
		self.assertIn("## Skill: prosally-node-types-and-flow-rules", system)
		self.assertIn("serviceTask: a PLATFORM OPERATION", system)

	def test_a_deprecated_skill_is_not_appended(self):
		_upsert_both_skills()
		frappe.db.set_value("AI Skill", patch.NODE_FLOW_SKILL, "status", "Deprecated")
		scope = {"_system": ""}
		exec(patch.SKILL_LINE, {"frappe": frappe}, scope)
		self.assertNotIn("prosally-node-types-and-flow-rules", scope["_system"])

	def test_running_twice_edits_each_script_once_and_rewrites_the_orchestrator_prompt(self):
		if not PROSALLY:
			self.skipTest("ProsAlly is not on this site")
		_upsert_both_skills()
		frappe.db.set_value("AI Agent Configuration", PROSALLY, "system_prompt", "You are ProsAlly.")

		patch.execute()
		patch.execute()

		for pattern in patch.STAGES.values():
			name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
			if name:
				self.assertEqual(
					frappe.db.get_value("Server Script", name, "script").count(patch.SKILL_LINE), 1
				)
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", PROSALLY, "system_prompt"),
			patch.ORCHESTRATOR_PROMPT,
		)
		self.assertFalse(
			frappe.db.exists("AI Agent Enabled Skill", {"parent": PROSALLY, "skill": earlier.BPMN_SKILL})
		)


def _upsert_both_skills():
	with mock_patch.object(patch, "AGENT_ID", "no_such_agent"):
		patch.execute()
	frappe.db.set_value("AI Skill", patch.NODE_FLOW_SKILL, "status", "Active")
	for skill in earlier.SKILLS:
		if skill["skill_name"] == earlier.BPMN_SKILL:
			earlier._upsert_skill(skill)
