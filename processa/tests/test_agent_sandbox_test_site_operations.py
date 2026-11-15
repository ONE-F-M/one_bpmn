# Copyright (c) 2026, one-fm and contributors
"""The Testing Agent's two sandbox commands: their operation records, how their results settle, what is kept off the audit row."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import agent_callback as callback
from processa.agents_sandbox.sandbox import ops
from processa.patches.v1_0 import add_agent_sandbox_test_site_operations as patch_ops

OPERATION = "BPMN Connector Operation"
ACTIONS = ("prepare_site", "checkout_pr_head")


def _name(operation_id):
	return frappe.db.get_value(OPERATION, {"connector": "agent_sandbox", "operation_id": operation_id}, "name")


class TestOperationRecords(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Connector", "agent_sandbox"):
			self.skipTest("no agent_sandbox connector on this site")
		for operation_id in ACTIONS:
			if name := _name(operation_id):
				frappe.delete_doc(OPERATION, name, force=True, ignore_permissions=True)

	def test_both_are_created_as_slow_dispatch_operations_and_a_repeat_changes_nothing(self):
		patch_ops.execute()
		patch_ops.execute()
		for operation_id in ACTIONS:
			doc = frappe.get_doc(OPERATION, _name(operation_id))
			self.assertEqual((doc.execution_type, doc.handler_path, doc.enabled), ("Python Handler", patch_ops.HANDLER, 1))
		self.assertEqual(frappe.db.count(OPERATION, {"connector": "agent_sandbox", "operation_id": ["in", list(ACTIONS)]}), 2)

	def test_the_fields_match_what_the_sandbox_reads(self):
		patch_ops.execute()
		fields = {a: [r.field_name for r in frappe.get_doc(OPERATION, _name(a)).fields] for a in ACTIONS}
		self.assertEqual(fields["prepare_site"][:3], ["target_app", "git_branch", "work_item_description"])
		for name in ("run_id", "pr_number", "base_branch", "roles", "password"):
			self.assertIn(name, fields["prepare_site"])
		self.assertEqual(fields["checkout_pr_head"][-2:], ["run_id", "pr_number"])

	def test_neither_operation_edits_application_files(self):
		self.assertEqual({o["value"] for o in patch_ops.OPERATIONS}, set(ACTIONS))


class TestSettling(FrappeTestCase):
	def test_a_prepared_site_and_a_ready_head_complete_without_a_pull_request(self):
		self.assertEqual(callback._settled_fields("prepare_site", "prepared", "", {}), {"state": "completed"})
		self.assertEqual(callback._settled_fields("checkout_pr_head", "ready", "", {}), {"state": "completed"})

	def test_any_other_status_fails_and_keeps_the_reason(self):
		for action in ACTIONS:
			fields = callback._settled_fields(action, "failed", "", {"error": "migration failed on the pull request head"})
			self.assertEqual((fields["state"], fields["error_message"]), ("failed", "migration failed on the pull request head"))
		self.assertEqual(callback._settled_fields("prepare_site", "ready", "", {})["state"], "failed")

	def test_run_tests_and_the_pull_request_settle_as_before(self):
		self.assertEqual(callback._settled_fields("run_tests", "tests_passed", "", {}), {"state": "completed"})
		self.assertEqual(callback._settled_fields("open_pull_request", "tests_passed", "", {})["state"], "failed")

	def test_the_agent_is_told_the_result_or_the_failed_step_and_output(self):
		done = SimpleNamespace(
			state="completed", retry_of=None, error_message="", request_payload='{"action": "checkout_pr_head"}',
			result='{"status": "ready", "pr_head_sha": "abc", "timings_ms": {"total": 1}}',
		)
		text = callback._sandbox_run_answer(done)
		self.assertIn("checkout_pr_head succeeded", text)
		self.assertIn("abc", text)
		self.assertNotIn("timings_ms", text)
		failed = SimpleNamespace(
			state="failed", retry_of=None, error_message="migration failed", request_payload='{"action": "checkout_pr_head"}',
			result='{"step": "migrate", "migration_tail": "boom at patch x"}',
		)
		text = callback._sandbox_run_answer(failed)
		self.assertIn("failed at step migrate", text)
		self.assertIn("boom at patch x", text)


class TestSecretsAndRetries(FrappeTestCase):
	def test_the_password_is_a_secret_arg_and_these_actions_are_never_retried_from_the_stored_payload(self):
		self.assertIn("password", ops.SECRET_ARGS)
		for action in ACTIONS:
			run = SimpleNamespace(action=action, failure_class="env")
			with patch.object(ops.supervisor, "next_step", return_value={"action": "retry"}):
				self.assertFalse(ops.retry_eligible(run))
