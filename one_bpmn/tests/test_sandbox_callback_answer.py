# Copyright (c) 2026, one-fm and contributors
"""What a suspended agent is told when its sandbox tool call comes back.

run_tests is its own tool now and never opens a PR, so "tests passed" is its
completion, and either outcome has to carry the sandbox's output — a bare
"tests_failed" left the model unable to tell its change from the environment,
and it simply queued the same ten-minute run again.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import agent_callback as cb


def _run(action, state, result=None, error_message=None, pr_url=None):
	return frappe._dict(
		request_payload=frappe.as_json({"action": action}),
		state=state,
		error_message=error_message,
		pr_url=pr_url,
		result=frappe.as_json(result or {}),
	)


class TestSettledFields(FrappeTestCase):
	def test_run_tests_passing_is_completion_without_a_pr(self):
		self.assertEqual(cb._settled_fields("run_tests", "tests_passed", "", {}), {"state": "completed"})

	def test_run_tests_failing_keeps_the_reason(self):
		fields = cb._settled_fields("run_tests", "tests_failed", "", {})
		self.assertEqual(fields["state"], "failed")
		self.assertEqual(fields["error_message"], "tests_failed")

	def test_open_pull_request_still_needs_a_url_to_complete(self):
		self.assertEqual(
			cb._settled_fields("open_pull_request", "tests_passed", "https://x/pull/1", {}),
			{"state": "completed", "pr_url": "https://x/pull/1"},
		)
		fields = cb._settled_fields("open_pull_request", "tests_passed", "", {"pr_error": "boom"})
		self.assertEqual(fields, {"state": "failed", "error_message": "boom"})

	def test_a_pr_opened_despite_failing_tests_is_kept_on_a_failed_run(self):
		fields = cb._settled_fields("open_pull_request", "tests_failed", "https://x/pull/2", {})
		self.assertEqual(fields["state"], "failed")
		self.assertEqual(fields["pr_url"], "https://x/pull/2")


class TestSandboxRunAnswer(FrappeTestCase):
	def test_failed_tests_carry_the_sandbox_output(self):
		run = _run("run_tests", "failed", {"stderr_tail": "x" * 3000 + "\nLinkValidationError: Warehouse Type"}, "tests_failed")
		answer = cb._sandbox_run_answer(run)
		self.assertTrue(answer.startswith("Tests failed (tests_failed)."))
		self.assertIn("LinkValidationError: Warehouse Type", answer)
		self.assertNotIn("x" * 1600, answer)  # tail is bounded

	def test_passing_tests_are_not_reported_as_a_missing_pr(self):
		answer = cb._sandbox_run_answer(_run("run_tests", "completed", {"stdout_tail": "Ran 12 tests OK"}))
		self.assertTrue(answer.startswith("Tests passed."))
		self.assertIn("Ran 12 tests OK", answer)
		self.assertNotIn("pull request", answer)

	def test_pull_request_answers_are_unchanged(self):
		self.assertEqual(
			cb._sandbox_run_answer(_run("open_pull_request", "completed", pr_url="https://x/pull/1")),
			"Pull request opened: https://x/pull/1",
		)
		answer = cb._sandbox_run_answer(
			_run("open_pull_request", "failed", {"stderr_tail": "FAILED (errors=1)"}, "tests_failed", "https://x/pull/2")
		)
		self.assertIn("A pull request was still opened for review, despite the failure: https://x/pull/2", answer)
		self.assertIn("FAILED (errors=1)", answer)

	def test_no_output_adds_nothing(self):
		self.assertEqual(cb._sandbox_run_answer(_run("run_tests", "failed", {}, "tests_failed")), "Tests failed (tests_failed).")
