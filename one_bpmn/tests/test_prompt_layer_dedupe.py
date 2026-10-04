# Copyright (c) 2026, one-fm and contributors
"""Stable instructions must exist in exactly one role.

A block repeated in the user role is paid for again on every turn — the system
role is the cached one — and two copies drift apart the moment either is edited.
The scan at the end is the guard: it walks the real agents on this site and
fails if an assembled turn would carry the same instruction block twice.
"""

import html
import re
import unittest

import frappe

from one_bpmn.agents.context_assembler import (
	_DUPLICATE_MIN_CHARS,
	drop_duplicated_instructions,
)

_LONG = (
	"Work this turn by calling tools, then ALWAYS finish by calling finalize "
	"exactly once — finalize is what the user actually sees, so a turn without "
	"it is a lost turn. Never answer in prose: your plain-text output is discarded."
)


class TestPromptLayerDedupe(unittest.TestCase):
	def test_duplicated_block_is_dropped_from_the_user_role(self):
		system = f"You are LuCrusher.\n\n## Working a turn\n{_LONG}"
		user = f"Conversation so far:\nUser: hello\n\n{_LONG}\n\nUser message: hello"
		out = drop_duplicated_instructions(system, user)
		self.assertNotIn(_LONG, out)
		self.assertIn("User message: hello", out)
		self.assertIn("Conversation so far:", out)

	def test_indentation_does_not_hide_a_duplicate(self):
		system = f"rules:\n\n{_LONG}"
		user = "    " + _LONG.replace(" ", "  ") + "\n\nUser message: hi"
		self.assertNotIn("finalize", drop_duplicated_instructions(system, user))

	def test_unique_user_text_is_kept(self):
		system = "You are LuCrusher."
		user = f"{_LONG}\n\nUser message: hi"
		self.assertIn(_LONG, drop_duplicated_instructions(system, user))

	def test_short_repeats_survive(self):
		"""A heading or a label repeats legitimately; only blocks are dropped."""
		system = "Answer in JSON."
		user = "Answer in JSON.\n\nUser message: hi"
		out = drop_duplicated_instructions(system, user)
		self.assertIn("Answer in JSON.", out)
		self.assertLess(len("Answer in JSON."), _DUPLICATE_MIN_CHARS)

	def test_empty_inputs_are_returned_unchanged(self):
		self.assertEqual(drop_duplicated_instructions("", "abc"), "abc")
		self.assertEqual(drop_duplicated_instructions("abc", ""), "")

	def test_no_live_agent_ships_the_same_instruction_block_twice(self):
		"""String scan over this site's AI shapes.

		Reads each AI Agent Task's own prompts out of the stored diagram and
		checks the pair the dispatcher would assemble. A failure names the shape,
		because the fix is to delete the block from ONE of the two roles.
		"""
		offenders = []
		for model in frappe.get_all("BPMN Process Model", pluck="name"):
			xml = frappe.db.get_value("BPMN Process Model", model, "bpmn_xml") or ""
			for match in re.finditer(r"<bpmn:serviceTask\b[^>]*>", xml):
				tag = match.group(0)
				system = re.search(r'aiSystemPrompt="([^"]*)"', tag)
				user = re.search(r'aiUserPrompt="([^"]*)"', tag)
				if not (system and user):
					continue
				shape = re.search(r'id="([^"]+)"', tag)
				assembled = drop_duplicated_instructions(
					html.unescape(system.group(1)),
					html.unescape(user.group(1)),
				)
				for block in assembled.split("\n\n"):
					normalised = " ".join(block.split())
					if len(normalised) < _DUPLICATE_MIN_CHARS:
						continue
					if normalised in " ".join(html.unescape(system.group(1)).split()):
						offenders.append(f"{model}:{shape.group(1) if shape else '?'}")
						break
		self.assertEqual(offenders, [], f"instruction blocks duplicated across roles: {offenders}")
