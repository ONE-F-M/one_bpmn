# Copyright (c) 2026, one-fm and contributors
"""A configuration cannot be saved with a model that has no provider, and the bench listing finds old ones."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.commands.agent_providers import configs_without_provider

ORPHAN_MODEL = "orphan-model-no-provider-test"
LINKED_MODEL = "linked-model-with-provider-test"


class TestAgentModelWithoutProvider(FrappeTestCase):
	def setUp(self):
		for name, provider in ((ORPHAN_MODEL, None), (LINKED_MODEL, "OpenAI")):
			if not frappe.db.exists("AI Model", name):
				frappe.get_doc({
					"doctype": "AI Model", "model_name": name, "provider": provider, "enable_model": 0,
				}).insert(ignore_permissions=True)

	def _config(self, agent_id: str, ai_model: str):
		return frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": agent_id.replace("_", " ").title(),
			"agent_id": agent_id,
			"agent_framework": "LangGraph",
			"system_prompt": "You are a test agent.",
			"ai_model": ai_model,
		})

	def test_model_without_provider_refuses_save_and_names_model(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._config("no_provider_agent_test", ORPHAN_MODEL).insert(ignore_permissions=True)
		self.assertIn(ORPHAN_MODEL, str(ctx.exception))

	def test_model_with_provider_saves_and_derives_provider(self):
		doc = self._config("linked_provider_agent_test", LINKED_MODEL).insert(ignore_permissions=True)
		self.assertEqual(doc.ai_provider, "OpenAI")

	def test_listing_finds_config_written_around_validation(self):
		healthy = self._config("healthy_agent_test", LINKED_MODEL).insert(ignore_permissions=True)
		legacy = self._config("legacy_orphan_agent_test", LINKED_MODEL).insert(ignore_permissions=True)
		frappe.db.set_value("AI Agent Configuration", legacy.name, {"ai_model": ORPHAN_MODEL, "ai_provider": None})

		names = [row.name for row in configs_without_provider()]
		self.assertIn(legacy.name, names)
		self.assertNotIn(healthy.name, names)
