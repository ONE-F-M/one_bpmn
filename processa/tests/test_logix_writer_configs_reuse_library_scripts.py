# Copyright (c) 2026, one-fm and contributors
"""The library-script guidance reaches the Logix writer configurations' own system prompts."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_writer_configs_reuse_library_scripts as patch
from processa.patches.v1_0.logix_writer_reuses_library_scripts import GUIDANCE

FRAMEWORK = "Direct API"


class TestLogixWriterConfigsReuseLibraryScripts(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.names = {}
		for agent_id in patch.WRITER_AGENT_IDS:
			existing = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
			if existing:
				frappe.db.set_value("AI Agent Configuration", existing, "system_prompt", "You are Logix.")
				self.names[agent_id] = existing
				continue
			config = frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": f"Test {agent_id}",
					"agent_id": agent_id,
					"agent_framework": FRAMEWORK,
					"system_prompt": "You are Logix.",
				}
			).insert()
			self.names[agent_id] = config.name

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self, agent_id):
		return frappe.db.get_value("AI Agent Configuration", self.names[agent_id], "system_prompt")

	def test_both_writers_get_the_guidance_once(self):
		patch.execute()
		patch.execute()
		for agent_id in patch.WRITER_AGENT_IDS:
			with self.subTest(agent_id=agent_id):
				prompt = self._prompt(agent_id)
				self.assertTrue(prompt.startswith("You are Logix."))
				self.assertEqual(prompt.count(GUIDANCE), 1)
