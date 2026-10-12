# Copyright (c) 2026, one-fm and contributors
"""Prompt rule blocks are added and replaced one at a time, in any order, without touching the blocks around them."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import (
	coding_agents_use_batched_tools_and_evidence as batched,
	coding_agents_work_within_their_turns as turns,
	frontend_and_mobile_agents_search_and_read_less as search,
)
from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

BLOCK = "Title:\n- one rule\n- another rule\n"


class TestWithBlock(FrappeTestCase):
	def test_the_block_is_added_after_the_prompt(self):
		self.assertEqual(with_block("Do the job.", BLOCK), "Do the job.\n\nTitle:\n- one rule\n- another rule\n")

	def test_an_empty_prompt_becomes_the_block(self):
		self.assertEqual(with_block(None, BLOCK), BLOCK)

	def test_adding_it_twice_changes_nothing(self):
		once = with_block("Do the job.", BLOCK)
		self.assertEqual(with_block(once, BLOCK), once)

	def test_a_block_in_the_middle_is_replaced_and_the_blocks_after_it_are_kept(self):
		prompt = "Do the job.\n\nTitle:\n- old rule\n\nLater:\n- stays\n"
		result = with_block(prompt, BLOCK)
		self.assertNotIn("old rule", result)
		self.assertIn("Later:\n- stays", result)
		self.assertEqual(result.count("Title:"), 1)
		self.assertTrue(result.startswith("Do the job."))


class TestPatchesInAnyOrder(FrappeTestCase):
	def setUp(self):
		self.agent = next((a for a in ("Frontend Agent", "Mobile App Agent") if frappe.db.exists("AI Agent Configuration", a)), None)
		if not self.agent:
			self.skipTest("neither the Frontend nor the Mobile App agent is on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_rerunning_an_earlier_patch_keeps_the_blocks_added_after_it(self):
		frappe.db.set_value("AI Agent Configuration", self.agent, "system_prompt", "Do the job.", update_modified=False)
		for patch in (batched, turns, search):
			patch.execute()
		batched.execute()
		prompt = frappe.db.get_value("AI Agent Configuration", self.agent, "system_prompt")
		self.assertTrue(prompt.startswith("Do the job."))
		for marker in (batched.marker(), turns.marker(), search.marker(self.agent)):
			self.assertEqual(prompt.count(marker), 1, marker)
