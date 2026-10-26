# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""WI-002195: the phase tables and the confirmation section agree.

The patch rewrites three lines of LuCrusher's seeded system prompt so a
confirmation no longer asks for the draft to be sent again. The edit is checked
as a pure function of the text: anchored, applied once, blind to prompts that
do not carry the lines. When the site carries the agent, the real prompt is
shown to take the edit the same way.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0.lucrusher_confirmations_carry_no_draft import (
	_AGENT_ID,
	_REWRITES,
	rewrite_confirmation_lines,
)
from one_bpmn.one_bpmn.patches.v1_0.lucrusher_scan_digest_and_short_confirmations import (
	_PROMPT_BLOCK,
)

_SEEDED_EXCERPT = "\n".join(
	[
		"═══ PHASE 4 — TOPOLOGY ANALYSIS ═══",
		_REWRITES[0][0],
		'  • User wants changes → intent "TOPOLOGY_PROPOSAL" with revised topology.',
		"═══ PHASE 5 — MIGRATION TASKS ═══",
		_REWRITES[1][0],
		"═══ PHASE 6 — PROSALLY PROMPTS ═══",
		_REWRITES[2][0],
	]
)


class TestConfirmationLines(FrappeTestCase):
	def test_each_line_is_rewritten_once(self):
		updated, changed = rewrite_confirmation_lines(_SEEDED_EXCERPT)
		self.assertTrue(changed)
		for old, new in _REWRITES:
			self.assertNotIn(old, updated)
			self.assertEqual(updated.count(new), 1)

		again, changed_again = rewrite_confirmation_lines(updated)
		self.assertFalse(changed_again)
		self.assertEqual(again, updated)

	def test_neighbouring_lines_are_left_alone(self):
		updated, _ = rewrite_confirmation_lines(_SEEDED_EXCERPT)
		self.assertIn("═══ PHASE 4 — TOPOLOGY ANALYSIS ═══", updated)
		self.assertIn(
			'  • User wants changes → intent "TOPOLOGY_PROPOSAL" with revised topology.', updated
		)

	def test_a_prompt_without_the_lines_is_untouched(self):
		trimmed = f"You are LuCrusher.\n\n## Confirming a draft\n{_PROMPT_BLOCK}\n"
		updated, changed = rewrite_confirmation_lines(trimmed)
		self.assertFalse(changed)
		self.assertEqual(updated, trimmed)
		self.assertEqual(rewrite_confirmation_lines(""), ("", False))
		self.assertEqual(rewrite_confirmation_lines(None), ("", False))

	def test_new_lines_agree_with_the_confirmation_section(self):
		"""Both places now say the same thing: intent and response, nothing else."""
		self.assertIn("ONLY intent and response", _PROMPT_BLOCK)
		for _old, new in _REWRITES:
			self.assertIn("with intent and response only", new)
			self.assertIn("do not send", new)
		for intent, (_old, new) in zip(
			("TOPOLOGY_CONFIRMED", "MIGRATION_TASKS_CONFIRMED", "PROSALLY_PROMPT_CONFIRMED"),
			_REWRITES,
		):
			self.assertIn(intent, new)

	def test_the_real_prompt_on_this_site_takes_the_edit(self):
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _AGENT_ID}, "name")
		if not name:
			self.skipTest("this site has no LuCrusher configuration")
		prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
		updated, changed = rewrite_confirmation_lines(prompt)
		if not changed:
			# A hand-trimmed prompt (the BA site) carries none of the lines.
			for old, _new in _REWRITES:
				self.assertNotIn(old, prompt)
			return
		for old, _new in _REWRITES:
			self.assertNotIn(old, updated)
		self.assertEqual(rewrite_confirmation_lines(updated), (updated, False))
