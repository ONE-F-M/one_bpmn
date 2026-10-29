# Copyright (c) 2026, one-fm and contributors
"""ProsAlly names whether a process is executable in its confirmation and sets the IR flag when drawing."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import prosally_confirms_executable_or_not as patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID


class TestExecutableOrNot(FrappeTestCase):
	def setUp(self):
		self.config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not self.config:
			self.skipTest("ProsAlly is not on this site")
		patch.execute()

	def _prompt(self, sub_agent_id):
		return frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": self.config, "sub_agent_id": sub_agent_id}, "prompt_text"
		)

	def test_classifier_names_both_kinds_in_the_confirmation(self):
		prompt = self._prompt("intent_classifier")
		self.assertIn("non-executable process, a guide people follow", prompt)
		self.assertIn("executable process, one the system runs", prompt)

	def test_generator_sets_the_flag_and_loads_the_skill(self):
		prompt = self._prompt("process_generator")
		self.assertIn('"executable": false', prompt)
		self.assertIn(f"The {patch.SKILL} skill below", prompt)

	def test_generator_system_prompt_carries_the_skill(self):
		from one_bpmn.agents.prosally_helpers import prosally_config, stage_system_prompt

		system = stage_system_prompt(prosally_config(), "process_generator", patch.SKILLS_CONSTANT)
		self.assertIn("## Skill: " + patch.SKILL, system)
		self.assertIn("Lifecycle of a DocType", system)

	def test_running_twice_edits_each_prompt_once(self):
		patch.execute()
		self.assertEqual(self._prompt("intent_classifier").count(patch.CLASSIFIER_MARKER), 1)
		self.assertEqual(self._prompt("process_generator").count(patch.GENERATOR_MARKER), 1)
		names = frappe.db.get_value(
			"AI Agent Constant", {"parent": self.config, "constant_name": patch.SKILLS_CONSTANT}, "constant_value"
		)
		self.assertEqual(names.count(patch.SKILL), 1)
