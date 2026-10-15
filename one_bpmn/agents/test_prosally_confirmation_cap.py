# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The confirmation summary lists at most 8 steps and 6 settings (WI-003582)."""

import unittest

from one_bpmn.agents.prosally_helpers import (
	MAX_CONFIRMATION_SETTINGS,
	MAX_CONFIRMATION_STEPS,
	join_confirmation,
)


def _bullets(text: str, prefix: str) -> list:
	return [line for line in text.splitlines() if line.startswith(prefix)]


class TestConfirmationCap(unittest.TestCase):
	def test_limits_are_eight_steps_and_six_settings(self):
		self.assertEqual(MAX_CONFIRMATION_STEPS, 8)
		self.assertEqual(MAX_CONFIRMATION_SETTINGS, 6)

	def test_long_lists_are_trimmed(self):
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
		self.assertTrue(text.endswith("Shall I draw it?"))

	def test_short_lists_are_untouched(self):
		summary = {"intro": "Plan.", "steps": ["A", "B"], "settings": ["X"]}
		text = join_confirmation(summary, "Go?")
		self.assertEqual(len(_bullets(text, "- ")), 3)

	def test_blank_items_do_not_use_up_the_cap(self):
		steps = [""] * 5 + ["Step %d" % i for i in range(8)]
		text = join_confirmation({"intro": "Plan.", "steps": steps}, "Go?")
		self.assertEqual(len(_bullets(text, "- Step ")), 8)
