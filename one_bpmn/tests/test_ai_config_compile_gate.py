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
		self.provider = frappe.db.get_value("AI Provider", {"enabled": 1}, "name")
		if not self.provider:
			self.skipTest("no enabled AI Provider on this site")
		if not frappe.db.exists("AI Agent Configuration", TEST_CONFIG):
			frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": TEST_CONFIG,
				"agent_id": "zz_gate_test_agent",
				"agent_framework": "Direct API",
				"agent_type": "Background",
				"enabled": 1,
				"ai_provider": self.provider,
			}).insert(ignore_permissions=True)
			# Go-live is the Agent Creation Process's decision now, so
			# nothing stamps this Live synchronously on insert. The compile gate
			# under test only accepts Live configs, so put it there directly —
			# straight to the DB, so the instance the insert started cannot race
			# this for the document's timestamp.
			frappe.db.set_value(
				"AI Agent Configuration", TEST_CONFIG, "lifecycle_status", "Live",
				update_modified=False,
			)

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

	def test_saving_a_background_agent_does_not_stamp_it_live(self):
		"""Background agents used to skip the creation process and go Live
		from a controller hook. That was removed: every agent type walks
		the map, so a save must leave the lifecycle alone and let the process
		decide — otherwise the map's start condition is pre-empted and never
		sees the agent at Draft."""
		agent = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": "ZZ Gate Test Not Auto Live",
			"agent_id": "zz_gate_test_not_auto_live",
			"agent_framework": "Direct API",
			"agent_type": "Background",
			"enabled": 1,
			"ai_provider": self.provider,
		}).insert(ignore_permissions=True)
		try:
			self.assertNotEqual(
				frappe.db.get_value("AI Agent Configuration", agent.name, "lifecycle_status"),
				"Live",
				"the controller must not decide go-live — the map does",
			)
		finally:
			frappe.db.delete("BPMN Process Instance", {"context_docname": agent.name})
			frappe.db.delete("AI Agent Configuration", {"name": agent.name})

	def test_non_live_config_blocks_deployment(self):
		# WI-001652: deployment requires Live — the error names the state.
		parked = "ZZ Gate Test Parked"
		if not frappe.db.exists("AI Agent Configuration", parked):
			# No provider link, and nothing stamps it Live — either way not Live.
			frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": parked,
				"agent_id": "zz_gate_test_parked",
				"agent_framework": "Direct API",
				"agent_type": "Background",
				"enabled": 1,
			}).insert(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", parked, "lifecycle_status"),
			"Needs Attention",
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			_lint_ai_provider_config("", {"t": {"serviceType": "ai_agent", "aiAgentConfig": parked}})
		self.assertIn("Needs Attention", str(ctx.exception))
