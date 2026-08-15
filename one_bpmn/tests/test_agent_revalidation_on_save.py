# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Every save of an AI Agent Configuration re-proves the agent — structural
checks plus a LIVE provider test call (user ruling 2026-07-21: assume
nothing; a Live badge must mean the agent works now, not that it worked at
creation). Live + failing → Needs Attention with the reason; Needs Attention
+ passing → back to Live; Draft and Retired are never touched."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

TEST_CALL = "one_bpmn.agents.agent_provisioning._provider_test_call"


class TestAgentRevalidationOnSave(FrappeTestCase):
	def setUp(self):
		frappe.flags.test_agent_revalidation = True
		suffix = frappe.generate_hash(length=6)
		self.creds = frappe.get_doc({
			"doctype": "AI Provider Credentials",
			"provider_name": f"Reval Test Creds {suffix}",
			"provider_type": "Anthropic",
			"api_key": "test-key-not-real",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.model = frappe.get_doc({
			"doctype": "AI Model",
			"model_name": f"reval-test-model-{suffix}",
			"ai_provider_credentials": self.creds.name,
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.flags.test_agent_revalidation = False

	def _make_agent(self, **overrides):
		suffix = frappe.generate_hash(length=6)
		values = {
			"doctype": "AI Agent Configuration",
			"agent_name": f"Reval Agent {suffix}",
			"agent_id": f"reval_agent_{suffix}",
			"agent_type": "Background",
			"agent_framework": "Direct API",
			"system_prompt": "You are a test agent.",
			"ai_model": self.model.name,
			"enabled": 1,
		}
		values.update(overrides)
		# Insert with a passing provider so setup state is deterministic.
		with patch(TEST_CALL, return_value=(True, "OK")):
			return frappe.get_doc(values).insert(ignore_permissions=True)

	def test_live_agent_parks_when_provider_call_fails(self):
		agent = self._make_agent()
		self.assertEqual(agent.lifecycle_status, "Live")  # Background auto-live

		with patch(TEST_CALL, return_value=(False, "401 invalid api key")):
			agent.save(ignore_permissions=True)

		self.assertEqual(agent.lifecycle_status, "Needs Attention")
		self.assertIn("401 invalid api key", agent.needs_attention_reason)
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", agent.name, "lifecycle_status"),
			"Needs Attention",
		)

	def test_parked_agent_self_heals_when_provider_call_passes(self):
		agent = self._make_agent()
		with patch(TEST_CALL, return_value=(False, "down")):
			agent.save(ignore_permissions=True)
		self.assertEqual(agent.lifecycle_status, "Needs Attention")

		with patch(TEST_CALL, return_value=(True, "OK")):
			agent.save(ignore_permissions=True)

		self.assertEqual(agent.lifecycle_status, "Live")
		self.assertFalse(agent.needs_attention_reason)

	def test_retired_is_untouched(self):
		# Retired is a deliberate manual state: neither the Background
		# auto-lifecycle nor the on-save revalidation may resurrect or park it.
		# (Draft is only reachable for Chat agents mid-creation; the creation
		# process owns that transition and the revalidation guard skips it.)
		agent = self._make_agent()
		frappe.db.set_value("AI Agent Configuration", agent.name, "lifecycle_status", "Retired")
		agent.reload()

		with patch(TEST_CALL, return_value=(False, "down")) as mocked:
			agent.save(ignore_permissions=True)

		self.assertEqual(agent.lifecycle_status, "Retired")
		mocked.assert_not_called()

	def test_empty_prompt_background_agent_is_only_credential_tested(self):
		# WI-001650 provider-grant pattern: Background agent with a
		# deliberately empty prompt must stay Live while its credentials work.
		agent = self._make_agent(system_prompt="")
		self.assertEqual(agent.lifecycle_status, "Live")

		with patch(TEST_CALL, return_value=(True, "OK")):
			agent.save(ignore_permissions=True)

		self.assertEqual(agent.lifecycle_status, "Live")

	def test_revalidation_skipped_without_test_opt_in(self):
		agent = self._make_agent()
		frappe.flags.test_agent_revalidation = False
		try:
			with patch(TEST_CALL, return_value=(False, "down")) as mocked:
				agent.save(ignore_permissions=True)
			mocked.assert_not_called()
			self.assertEqual(agent.lifecycle_status, "Live")
		finally:
			frappe.flags.test_agent_revalidation = True
