# Copyright (c) 2026, one-fm and contributors
"""No agent prompt may tell the model it cannot see the conversation.

The dispatcher now puts the person's message at the end of the prompt, so that
sentence is false — and it was load-bearing: it is why ProsAlly's and Logix's
prompts also forbid asking the user to repeat themselves. A map still carrying
it hands the model the message and denies it in the same breath.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_agent_prompt_hygiene
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0.drop_cannot_see_conversation import (
	OLD_SENTENCES,
	execute,
)

PHRASE = "cannot see the conversation"


class TestNoMapDeniesTheMessage(FrappeTestCase):
	def _maps(self):
		return [m for m in OLD_SENTENCES if frappe.db.exists("BPMN Process Model", m)]

	def test_the_phrase_is_gone_from_the_diagram_and_the_compiled_spec(self):
		"""Both, because the engine runs the spec and the editor shows the
		diagram — a rewrite that misses either one is half done."""
		maps = self._maps()
		if not maps:
			self.skipTest("neither chat map is installed")
		for model in maps:
			with self.subTest(model=model):
				xml, spec = frappe.db.get_value(
					"BPMN Process Model", model, ["bpmn_xml", "serialized_spec"]
				)
				self.assertNotIn(PHRASE, xml or "")
				self.assertNotIn(PHRASE, spec or "")

	def test_running_the_patch_again_changes_nothing(self):
		"""It runs on every migrate of a site that has not had it, and must be
		harmless on one that has — including a site whose map arrived by import
		already reading the new way."""
		maps = self._maps()
		if not maps:
			self.skipTest("neither chat map is installed")
		before = {m: frappe.db.get_value("BPMN Process Model", m, "bpmn_xml") for m in maps}

		execute()

		for model in maps:
			self.assertEqual(frappe.db.get_value("BPMN Process Model", model, "bpmn_xml"), before[model])

	def test_the_patch_is_declared(self):
		"""A patch file with no line in patches.txt never runs, and nothing
		says so — the failure is silent on every site that needed it."""
		import os

		patches = open(os.path.join(frappe.get_app_path("one_bpmn"), "patches.txt")).read()
		self.assertIn("one_bpmn.one_bpmn.patches.v1_0.drop_cannot_see_conversation", patches)
