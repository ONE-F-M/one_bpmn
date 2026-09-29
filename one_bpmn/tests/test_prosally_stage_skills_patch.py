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
		system = _run_line("Stage prompt.", patch.STAGE_SKILLS)
		self.assertTrue(system.startswith("Stage prompt."))
		self.assertIn("## Skill: bpmn-modelling-rules-and-ir-schema", system)
		self.assertIn("## Lane fidelity", system)
		self.assertIn("## Skill: prosally-node-types-and-flow-rules", system)
		self.assertIn("serviceTask: a PLATFORM OPERATION", system)

	def test_only_the_skills_named_in_the_stage_constant_are_appended(self):
		_upsert_both_skills()
		system = _run_line("", earlier.BPMN_SKILL)
		self.assertIn("## Skill: bpmn-modelling-rules-and-ir-schema", system)
		self.assertNotIn("prosally-node-types-and-flow-rules", system)

	def test_a_stage_with_no_constant_appends_nothing(self):
		_upsert_both_skills()
		scope = {"_system": "Stage prompt.", "_cfg": {"constants": {}}}
		exec(patch.skill_line("generate_skills"), {"frappe": frappe}, scope)
		self.assertEqual(scope["_system"], "Stage prompt.")

	def test_a_deprecated_skill_is_not_appended(self):
		_upsert_both_skills()
		frappe.db.set_value("AI Skill", patch.NODE_FLOW_SKILL, "status", "Deprecated")
		self.assertNotIn("prosally-node-types-and-flow-rules", _run_line("", patch.STAGE_SKILLS))

	def test_running_twice_edits_each_script_once_and_rewrites_the_orchestrator_prompt(self):
		if not PROSALLY:
			self.skipTest("ProsAlly is not on this site")
		_upsert_both_skills()
		frappe.db.set_value("AI Agent Configuration", PROSALLY, "system_prompt", "You are ProsAlly.")

		patch.execute()
		patch.execute()

		for sub_agent_id, pattern in patch.STAGES.items():
			name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
			if name:
				line = patch.skill_line(patch.STAGE_CONSTANTS[sub_agent_id])
				self.assertEqual(frappe.db.get_value("Server Script", name, "script").count(line), 1)
		for constant in patch.STAGE_CONSTANTS.values():
			rows = frappe.get_all(
				"AI Agent Constant", filters={"parent": PROSALLY, "constant_name": constant}, pluck="constant_value"
			)
			self.assertEqual(rows, [patch.STAGE_SKILLS])
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", PROSALLY, "system_prompt"),
			patch.ORCHESTRATOR_PROMPT,
		)
		self.assertFalse(
			frappe.db.exists("AI Agent Enabled Skill", {"parent": PROSALLY, "skill": earlier.BPMN_SKILL})
		)


def _run_line(system: str, skills: str) -> str:
	"""Run the generate stage's skill line the way the shape-tool exec does, with *skills* as its constant."""
	scope = {"_system": system, "_cfg": {"constants": {"generate_skills": skills}}}
	exec(patch.skill_line("generate_skills"), {"frappe": frappe}, scope)
	return scope["_system"]


def _upsert_both_skills():
	with mock_patch.object(patch, "AGENT_ID", "no_such_agent"):
		patch.execute()
	frappe.db.set_value("AI Skill", patch.NODE_FLOW_SKILL, "status", "Active")
	for skill in earlier.SKILLS:
		if skill["skill_name"] == earlier.BPMN_SKILL:
			earlier._upsert_skill(skill)
