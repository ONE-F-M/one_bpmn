# Copyright (c) 2026, one-fm and contributors
"""The editor reads and writes an agent's sandbox settings without them reaching the task at dispatch."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agent_config_resolver as resolver

ATTRS = ("aiSandboxUseJob", "aiSandboxRetryOnTestFailure", "aiRequireReproduction")


class TestSandboxSettingsInTheEditor(FrappeTestCase):
	def setUp(self):
		self.agent = next(
			(
				a
				for a in ("Dev Agent", "Frontend Agent", "Mobile App Agent")
				if frappe.db.exists("AI Agent Configuration", a)
			),
			None,
		)
		if not self.agent:
			self.skipTest("no coding agent is on this site")
		# Saving an agent commits somewhere along the way, which would keep these edits on a real agent past the rollback.
		self.no_commit = patch.object(frappe.db, "commit")
		self.no_commit.start()

	def tearDown(self):
		self.no_commit.stop()
		frappe.db.rollback()
		super().tearDown()

	def _set(self, use_job, retry, reproduction):
		frappe.db.set_value(
			"AI Agent Configuration",
			self.agent,
			{
				"sandbox_use_job": use_job,
				"sandbox_retry_on_test_failure": retry,
				"require_reproduction": reproduction,
			},
			update_modified=False,
		)

	def test_the_editor_read_returns_the_three_settings_as_numbers(self):
		self._set(1, 0, 1)
		fields = resolver.get_agent_config_for_shape(self.agent)
		self.assertEqual([fields[attr] for attr in ATTRS], [1, 0, 1])

	def test_an_unticked_setting_is_returned_as_zero_not_left_out(self):
		self._set(0, 0, 0)
		fields = resolver.get_agent_config_for_shape(self.agent)
		self.assertEqual([fields[attr] for attr in ATTRS], [0, 0, 0])

	def test_they_are_not_overlaid_onto_the_task_at_dispatch(self):
		self._set(1, 1, 1)
		overlay = resolver.config_field_map(self.agent)
		for attr in ATTRS:
			self.assertNotIn(attr, overlay)

	def test_the_editor_writes_them_back(self):
		self._set(0, 1, 0)
		resolver.update_agent_config_from_shape(
			self.agent,
			{"aiSandboxUseJob": 1, "aiSandboxRetryOnTestFailure": "0", "aiRequireReproduction": True},
		)
		saved = frappe.db.get_value(
			"AI Agent Configuration",
			self.agent,
			["sandbox_use_job", "sandbox_retry_on_test_failure", "require_reproduction"],
		)
		self.assertEqual(list(saved), [1, 0, 1])

	def test_saving_something_else_leaves_them_alone(self):
		self._set(1, 0, 1)
		resolver.update_agent_config_from_shape(self.agent, {"aiTemperature": 0.3})
		saved = frappe.db.get_value(
			"AI Agent Configuration",
			self.agent,
			["sandbox_use_job", "sandbox_retry_on_test_failure", "require_reproduction"],
		)
		self.assertEqual(list(saved), [1, 0, 1])

	def test_an_unknown_agent_reads_as_nothing(self):
		self.assertEqual(resolver.config_sandbox("No Such Agent"), {})
