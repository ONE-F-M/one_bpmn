# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001650: every AI shape must be backed by an AI Agent Configuration."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _lint_ai_provider_config

TEST_CONFIG = "ZZ Gate Test Agent"


class TestAiConfigCompileGate(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("AI Agent Configuration", TEST_CONFIG):
			frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": TEST_CONFIG,
				"agent_id": "zz_gate_test_agent",
				"agent_framework": "Direct API",
				# Background: must NOT trip the chat-agent creation trigger.
				"agent_type": "Background",
				"enabled": 1,
			}).insert(ignore_permissions=True)

	def test_raw_ai_task_is_blocked(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_lint_ai_provider_config("", {"raw_task": {"serviceType": "ai_agent", "aiProvider": "Claude"}})
		self.assertIn("raw_task", str(ctx.exception))
		self.assertIn("WI-001650", str(ctx.exception))

	def test_raw_selector_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			_lint_ai_provider_config("", {"sel": {"serviceType": "ai_task_selector", "aiProvider": "Claude"}})

	def test_linked_shape_passes(self):
		_lint_ai_provider_config("", {
			"ok_task": {"serviceType": "ai_agent", "aiAgentConfig": TEST_CONFIG},
			"ok_sel": {"serviceType": "ai_task_selector", "aiAgentConfig": TEST_CONFIG},
		})

	def test_link_to_missing_or_disabled_config_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			_lint_ai_provider_config("", {"t": {"serviceType": "ai_agent", "aiAgentConfig": "No Such Config 404"}})
		frappe.db.set_value("AI Agent Configuration", TEST_CONFIG, "enabled", 0)
		try:
			with self.assertRaises(frappe.ValidationError):
				_lint_ai_provider_config("", {"t": {"serviceType": "ai_agent", "aiAgentConfig": TEST_CONFIG}})
		finally:
			frappe.db.set_value("AI Agent Configuration", TEST_CONFIG, "enabled", 1)

	def test_non_ai_shapes_are_ignored(self):
		_lint_ai_provider_config("", {"script": {"serviceType": "update_field"}})
