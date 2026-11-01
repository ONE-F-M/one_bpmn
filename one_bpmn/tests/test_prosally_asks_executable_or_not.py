# Copyright (c) 2026, one-fm and contributors
"""ProsAlly asks whether to draw as executable or non-executable instead of deciding the kind itself."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import prosally_asks_executable_or_not as patch
from one_bpmn.one_bpmn.patches.v1_0 import prosally_confirms_executable_or_not as earlier
from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID


class TestAsksExecutableOrNot(FrappeTestCase):
	def setUp(self):
		self.config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not self.config:
			self.skipTest("ProsAlly is not on this site")
		earlier.execute()
		patch.execute()

	def _prompt(self, sub_agent_id):
		return frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": self.config, "sub_agent_id": sub_agent_id}, "prompt_text"
		)

	def test_classifier_treats_an_unchosen_kind_as_incomplete(self):
		prompt = self._prompt("intent_classifier")
		self.assertIn(patch.CLASSIFIER_MARKER, prompt)
		self.assertIn("classify as INCOMPLETE and write in reason: needs the kind of process", prompt)

	def test_classifier_no_longer_decides_the_kind_itself(self):
		prompt = self._prompt("intent_classifier")
		self.assertNotIn("because it follows", prompt)
		self.assertNotIn(earlier.CLASSIFIER_NEW, prompt)
		self.assertIn("which kind the person chose", prompt)

	def test_clarifier_asks_the_kind_with_two_options(self):
		prompt = self._prompt("clarifier")
		self.assertIn(patch.QUESTION, prompt)
		self.assertIn('"Executable" and "Non-executable"', prompt)

	def test_running_twice_edits_each_prompt_once(self):
		patch.execute()
		self.assertEqual(self._prompt("intent_classifier").count(patch.CLASSIFIER_MARKER), 1)
		self.assertEqual(self._prompt("clarifier").count(patch.CLARIFIER_MARKER), 1)
