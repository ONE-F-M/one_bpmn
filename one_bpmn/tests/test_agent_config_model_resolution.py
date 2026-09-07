# Copyright (c) 2026, one-fm and contributors
"""``get_agent_config`` must return the model the agent is configured with.

The field was in the query but missing from the dict the function returned, so
every caller that resolved an adapter through it — the provider test call that
gates an agent going Live among them — fell back to a default model name that
is not an ``AI Model`` record. No record means no API key, and the call died
with "Could not resolve authentication method", which reads like a missing
credential rather than a dropped field.

The cache made it durable: it is invalidated only on save, so a dict built
before a fix survives one.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import (
	get_agent_config,
)


class TestAgentConfigModelResolution(FrappeTestCase):
	def _live_configs(self):
		"""Enabled configs that name both an agent_id and a model."""
		return [
			r
			for r in frappe.get_all(
				"AI Agent Configuration",
				filters={"enabled": 1},
				fields=["name", "agent_id", "ai_model"],
			)
			if r.agent_id and r.ai_model
		]

	def test_returned_config_carries_the_configured_model(self):
		configs = self._live_configs()
		if not configs:
			self.skipTest("no enabled agent configuration names a model on this site")

		mismatched = []
		for row in configs:
			# The cache is keyed by agent_id and only cleared on save, so a stale
			# entry would mask the very thing under test.
			frappe.cache.delete_value(f"agent_config:{row.agent_id}")
			got = (get_agent_config(row.agent_id) or {}).get("ai_model")
			if got != row.ai_model:
				mismatched.append(f"{row.name}: expected {row.ai_model!r}, got {got!r}")

		self.assertFalse(
			mismatched,
			"get_agent_config dropped the configured model: " + "; ".join(mismatched),
		)

	def test_ai_model_key_is_present_even_when_unset(self):
		"""Absent and None are different: a missing key silently takes the
		factory's default branch, where a present-but-None value does not."""
		row = frappe.db.get_value(
			"AI Agent Configuration", {"enabled": 1}, ["agent_id"], as_dict=True
		)
		if not row or not row.agent_id:
			self.skipTest("no enabled agent configuration on this site")

		frappe.cache.delete_value(f"agent_config:{row.agent_id}")
		config = get_agent_config(row.agent_id)
		self.assertIn("ai_model", config)

	def test_unknown_agent_still_returns_none(self):
		self.assertIsNone(get_agent_config("no-such-agent-id-at-all"))
