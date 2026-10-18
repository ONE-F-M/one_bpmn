# Copyright (c) 2026, one-fm and contributors
"""An agent whose open_pull_request failed is not allowed to call it again until it has changed something or run the tests."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import repeat_open_pull_request_without_progress_error as gate

INSTANCE = "pr-retry-inst"
ERROR = "tests_failed; pull request not opened: no changes against staging"


def _row(action, state="completed", failure_class="", error=""):
	doc = frappe.get_doc(
		{
			"doctype": "Agent Sandbox Run", "state": state, "action": action, "failure_class": failure_class or None,
			"error_message": error, "target_app": "one_fm", "git_branch": "staging", "caller_instance": INSTANCE,
			"request_payload": json.dumps({"action": action, "args": {}}),
		}
	)
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)


def _instance():
	return frappe._dict(name=INSTANCE, process_model="Mobile App Agent")


class TestOpenPullRequestNoProgress(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_second_attempt_straight_after_a_failure_is_refused_with_the_error(self):
		_row("open_pull_request", "failed", "code", ERROR)
		message = gate(_instance(), "open_pull_request")
		self.assertIn("no changes against staging", message)
		self.assertIn("instead of retrying", message)

	def test_reading_in_between_does_not_count_as_progress(self):
		_row("open_pull_request", "failed", "code", ERROR)
		_row("read_file")
		_row("list_files")
		self.assertIsNotNone(gate(_instance(), "open_pull_request"))

	def test_a_completed_edit_since_allows_another_attempt(self):
		_row("open_pull_request", "failed", "code", ERROR)
		_row("apply_edits")
		self.assertIsNone(gate(_instance(), "open_pull_request"))

	def test_a_failed_edit_does_not_count(self):
		_row("open_pull_request", "failed", "code", ERROR)
		_row("edit_file", "failed", "code", "old_string not found")
		self.assertIsNotNone(gate(_instance(), "open_pull_request"))

	def test_a_test_run_since_allows_another_attempt_whatever_it_found(self):
		_row("open_pull_request", "failed", "code", ERROR)
		_row("run_tests", "failed", "code", "tests_failed")
		self.assertIsNone(gate(_instance(), "open_pull_request"))

	def test_a_network_failure_may_be_retried_at_once(self):
		_row("open_pull_request", "failed", "infra", "The sandbox call timed out")
		self.assertIsNone(gate(_instance(), "open_pull_request"))

	def test_a_run_whose_last_attempt_succeeded_is_not_held(self):
		_row("open_pull_request", "completed")
		self.assertIsNone(gate(_instance(), "open_pull_request"))

	def test_a_first_attempt_and_other_actions_are_not_held(self):
		self.assertIsNone(gate(_instance(), "open_pull_request"))
		_row("open_pull_request", "failed", "code", ERROR)
		self.assertIsNone(gate(_instance(), "run_tests"))
		self.assertIsNone(gate(None, "open_pull_request"))

	def test_it_applies_to_every_agent_not_only_the_bug_pipeline(self):
		_row("open_pull_request", "failed", "code", ERROR)
		for agent in ("Dev Agent", "Frontend Agent", "Mobile App Agent"):
			self.assertIsNotNone(gate(frappe._dict(name=INSTANCE, process_model=agent), "open_pull_request"), agent)
