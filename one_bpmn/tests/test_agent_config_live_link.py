# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001637 live-link amendment: config authoritative at dispatch + write-back."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	resolve_dispatch_overrides,
	update_agent_config_from_shape,
)

TEST_CONFIG = "ZZ Live Link Test Agent"


class TestAgentConfigLiveLink(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("AI Agent Configuration", TEST_CONFIG):
			frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": TEST_CONFIG,
				"agent_id": "zz_live_link_test_agent",
				"agent_framework": "Direct API",
				# Background: must NOT trip the chat-agent creation trigger.
				"agent_type": "Background",
				"system_prompt": "Original prompt.",
				"temperature": 0.5,
				"max_tokens": 512,
			}).insert(ignore_permissions=True)

	def test_dispatch_overrides_return_live_values(self):
		overrides = resolve_dispatch_overrides(TEST_CONFIG)
		self.assertEqual(overrides.get("aiSystemPrompt"), "Original prompt.")
		self.assertEqual(overrides.get("aiTemperature"), 0.5)
		self.assertEqual(overrides.get("aiMaxTokens"), 512)

	def test_dispatch_overrides_missing_config_falls_back_empty(self):
		self.assertEqual(resolve_dispatch_overrides("No Such Config 404"), {})
		self.assertEqual(resolve_dispatch_overrides(""), {})

	def test_dispatch_merge_prefers_config_over_shape(self):
		# The dispatchers overlay overrides onto the shape's copies.
		task_cfg = {"aiSystemPrompt": "stale shape copy", "aiOutputVariable": "out"}
		merged = {**task_cfg, **resolve_dispatch_overrides(TEST_CONFIG)}
		self.assertEqual(merged["aiSystemPrompt"], "Original prompt.")
		# Shape-only fields survive untouched.
		self.assertEqual(merged["aiOutputVariable"], "out")

	def test_write_back_updates_config(self):
		result = update_agent_config_from_shape(
			TEST_CONFIG,
			{"aiSystemPrompt": "Edited from the dialog.", "aiTemperature": "0.9"},
		)
		self.assertTrue(result["ok"])
		self.assertIn("system_prompt", result["updated"])
		self.assertIn("temperature", result["updated"])
		# Not Live -> no re-provision.
		self.assertFalse(result["reprovisioned"])
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", TEST_CONFIG, "system_prompt"),
			"Edited from the dialog.",
		)

	def test_write_back_no_change_is_noop(self):
		prompt = frappe.db.get_value("AI Agent Configuration", TEST_CONFIG, "system_prompt")
		result = update_agent_config_from_shape(TEST_CONFIG, {"aiSystemPrompt": prompt})
		self.assertEqual(result["updated"], [])
		self.assertFalse(result["reprovisioned"])

	def test_write_back_ignores_unknown_fields(self):
		# WI-001655 inverted the old rule: aiModel IS the updatable pick now,
		# while aiProvider (derived from the model) and shape-only fields are
		# ignored. An invalid model name fails link validation on save.
		result = update_agent_config_from_shape(
			TEST_CONFIG, {"aiProvider": "Claude", "aiOutputVariable": "x"}
		)
		self.assertEqual(result["updated"], [])

	def test_write_back_requires_write_permission(self):
		self.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				update_agent_config_from_shape(TEST_CONFIG, {"aiSystemPrompt": "hacked"})
		finally:
			self.set_user("Administrator")
