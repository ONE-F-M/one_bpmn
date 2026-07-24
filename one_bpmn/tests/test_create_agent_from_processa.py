# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001648: create an AI Agent Configuration from the Processa editor."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import create_agent_configuration

NAME = "ZZ Processa Create Test"


class TestCreateAgentFromProcessa(FrappeTestCase):
	def tearDown(self):
		frappe.flags.in_migrate = False
		super().tearDown()

	def _payload(self, **overrides):
		payload = {
			"agent_name": NAME,
			"chat_mode_label": "ZZ Processa Create Test",
			"ai_provider_credentials": None,
			"system_prompt": "Test prompt.",
			"sample_prompts": [
				{"prompt": "hello", "expected_behaviour": "greets back"},
				{"prompt": "   ", "expected_behaviour": "blank - dropped"},
			],
		}
		payload.update(overrides)
		return payload

	def test_requires_create_permission(self):
		self.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				create_agent_configuration(self._payload())
		finally:
			self.set_user("Administrator")

	def test_requires_name_and_label(self):
		with self.assertRaises(frappe.ValidationError):
			create_agent_configuration(self._payload(agent_name=""))
		with self.assertRaises(frappe.ValidationError):
			create_agent_configuration(self._payload(chat_mode_label=""))

	def test_creates_chat_draft_with_scrubbed_id(self):
		# Suppress the BPMN insert trigger — a real creation-process run makes
		# live AI calls; the trigger's own behavior is covered by WI-001620.
		frappe.flags.in_migrate = True
		result = create_agent_configuration(self._payload())
		self.assertEqual(result["name"], NAME)
		self.assertEqual(result["agent_id"], "zz_processa_create_test")

		doc = frappe.get_doc("AI Agent Configuration", NAME)
		self.assertEqual(doc.agent_type, "Chat")
		self.assertEqual(doc.lifecycle_status, "Draft")
		self.assertEqual(doc.enabled, 1)
		# blank sample prompt rows are dropped
		self.assertEqual(len(doc.sample_prompts), 1)
		self.assertEqual(doc.sample_prompts[0].prompt, "hello")

	def test_eval_suite_generation_without_process_model(self):
		# WI-001648 relaxation: a suite can be generated before the chat map
		# is provisioned (process_model empty).
		if not frappe.db.exists("AI Provider Credentials", {"enabled": 1}):
			self.skipTest("no enabled AI Provider Credentials on this site")
		provider = frappe.db.get_value("AI Provider Credentials", {"enabled": 1}, "name")

		frappe.flags.in_migrate = True
		create_agent_configuration(self._payload(ai_provider_credentials=provider))
		frappe.flags.in_migrate = False

		from one_bpmn.agents.agent_provisioning import generate_eval_suite_for_agent

		suite = generate_eval_suite_for_agent(NAME)
		self.assertTrue(suite)
		cases = frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["name", "model"])
		self.assertEqual(len(cases), 1)
