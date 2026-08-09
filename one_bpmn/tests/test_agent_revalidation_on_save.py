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
		status = values.pop("lifecycle_status", "Live")
		values.update(overrides)
		# Insert with a passing provider so setup state is deterministic.
		with patch(TEST_CALL, return_value=(True, "OK")):
			doc = frappe.get_doc(values).insert(ignore_permissions=True)
		# WI-001969: Background agents used to be stamped Live by a controller
		# hook on save. Go-live is the Agent Creation Process's decision now, so
		# the starting state is set here rather than assumed — and set straight to
		# the DB so the process instance the insert started cannot race the test
		# for the document's timestamp.
		frappe.db.set_value(
			"AI Agent Configuration", doc.name, "lifecycle_status", status, update_modified=False
		)
		doc.reload()
		return doc

	def test_live_agent_parks_when_provider_call_fails(self):
		agent = self._make_agent()
		self.assertEqual(agent.lifecycle_status, "Live")

		with patch(TEST_CALL, return_value=(False, "401 invalid api key")):
			agent.save(ignore_permissions=True)

		self.assertEqual(agent.lifecycle_status, "Needs Attention")
		self.assertIn("401 invalid api key", agent.needs_attention_reason)
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", agent.name, "lifecycle_status"),
			"Needs Attention",
		)

	def test_a_parked_agent_is_handed_back_to_the_map_not_promoted(self):
		"""WI-001969: credentials working again is not a go-live. The controller
		used to stamp Live here, which made disable/re-enable a way around the
		adversarial gate; it now hands the agent to the Agent Creation Process,
		which runs that gate as a step in the diagram."""
		agent = self._make_agent()
		with patch(TEST_CALL, return_value=(False, "down")):
			agent.save(ignore_permissions=True)
		self.assertEqual(agent.lifecycle_status, "Needs Attention")

		with patch(TEST_CALL, return_value=(True, "OK")), patch(
			"one_bpmn.agents.agent_config_resolver._start_reprovision", return_value=True
		) as handoff:
			agent.save(ignore_permissions=True)

		self.assertTrue(handoff.called, "the map must be asked to re-review it")
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", agent.name, "lifecycle_status"),
			"Needs Attention",
			"only the map may promote",
		)

	def test_retired_is_untouched(self):
		# Retired is a deliberate manual state: the on-save revalidation may
		# neither resurrect nor park it. (Draft belongs to the creation process,
		# which every agent type walks since WI-001969, and the revalidation
		# guard skips that state too.)
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
