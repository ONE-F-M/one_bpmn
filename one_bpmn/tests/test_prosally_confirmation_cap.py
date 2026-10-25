# Copyright (c) 2026, one-fm and contributors
"""The confirmation summary lists at most 8 steps and 6 settings, and the classifier prompt asks for that."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.prosally_helpers import MAX_CONFIRMATION_SETTINGS, MAX_CONFIRMATION_STEPS, join_confirmation
from one_bpmn.one_bpmn.patches.v1_0 import prosally_caps_the_confirmation_summary as cap_patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID, SUITE_TITLE


def _bullets(text: str, prefix: str) -> list:
	return [line for line in text.splitlines() if line.startswith(prefix)]


class TestConfirmationCap(FrappeTestCase):
	def test_limits_are_eight_steps_and_six_settings(self):
		self.assertEqual((MAX_CONFIRMATION_STEPS, MAX_CONFIRMATION_SETTINGS), (8, 6))

	def test_long_lists_are_trimmed_and_say_how_many_were_left_out(self):
		summary = {
			"intro": "Plan.",
			"steps": ["Step %d" % i for i in range(20)],
			"settings": ["Setting %d" % i for i in range(15)],
		}
		text = join_confirmation(summary, "Shall I draw it?")
		self.assertEqual(len(_bullets(text, "- Step ")), 8)
		self.assertEqual(len(_bullets(text, "- Setting ")), 6)
		self.assertIn("- Step 7", text)
		self.assertNotIn("- Step 8", text)
		self.assertNotIn("- Setting 6", text)
		self.assertIn("and 12 more not listed here", text)
		self.assertIn("and 9 more not listed here", text)
		self.assertTrue(text.endswith("Shall I draw it?"))

	def test_a_list_at_the_cap_says_nothing_about_more(self):
		text = join_confirmation({"intro": "Plan.", "steps": ["Step %d" % i for i in range(8)]}, "Go?")
		self.assertEqual(len(_bullets(text, "- Step ")), 8)
		self.assertNotIn("more not listed", text)

	def test_short_lists_are_untouched(self):
		text = join_confirmation({"intro": "Plan.", "steps": ["A", "B"], "settings": ["X"]}, "Go?")
		self.assertEqual(len(_bullets(text, "- ")), 3)
		self.assertNotIn("more not listed", text)

	def test_blank_items_do_not_use_up_the_cap(self):
		steps = [""] * 5 + ["Step %d" % i for i in range(8)]
		text = join_confirmation({"intro": "Plan.", "steps": steps}, "Go?")
		self.assertEqual(len(_bullets(text, "- Step ")), 8)
		self.assertNotIn("more not listed", text)


class TestClassifierPromptAsksForTheCap(FrappeTestCase):
	def setUp(self):
		cap_patch.execute()
		self.config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not self.config:
			self.skipTest("ProsAlly is not on this site")

	def _prompt(self):
		return frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": self.config, "sub_agent_id": cap_patch.SUB_AGENT_ID}, "prompt_text"
		)

	def test_the_prompt_asks_for_eight_steps_and_six_settings_at_most(self):
		text = self._prompt()
		self.assertIn("never has more than 8", text)
		self.assertIn("List at most 6 settings", text)
		self.assertIn("Never list more than 8 steps or 6 settings", text)

	def test_running_the_patch_again_changes_nothing(self):
		before = self._prompt()
		cap_patch.execute()
		self.assertEqual(self._prompt(), before)

	def test_the_eval_case_is_added_once(self):
		if not frappe.db.exists("AI Eval Suite", {"title": SUITE_TITLE}):
			self.skipTest("the Prosally baseline suite is not on this site")
		cap_patch.execute()
		cap_patch.execute()
		self.assertEqual(frappe.db.count("AI Eval Case", {"title": cap_patch.CASE_TITLE}), 1)
