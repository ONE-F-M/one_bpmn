# Copyright (c) 2026, one-fm and contributors
"""A failed sandbox run is retried, handed back or stopped according to the class of its failure."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import agent_callback as cb
from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.connectors import agent_sandbox_reaper as reaper
from one_bpmn.one_bpmn.connectors import agent_sandbox_supervisor as supervisor
from one_bpmn.tests.test_agent_callback import CallbackCase


class FakeRun(frappe._dict):
	def db_set(self, field, value, **kwargs):
		self[field] = value


def failed_run(**fields) -> FakeRun:
	base = {
		"failure_class": "infra",
		"attempt": 1,
		"retry_of": None,
		"action": "run_tests",
		"work_item": None,
		"error_message": "it broke",
		"target_app": "one_fm",
		"git_branch": "staging",
	}
	return FakeRun({**base, **fields})


class TestEachFailureClass(FrappeTestCase):
	def test_infrastructure_is_retried_twice_with_a_longer_wait_each_time_then_stopped(self):
		steps = [supervisor.next_step(failed_run(attempt=n)) for n in (1, 2, 3)]
		self.assertEqual(
			[(s["action"], s["delay"]) for s in steps], [("retry", 15), ("retry", 60), ("stop", 0)]
		)
		self.assertEqual(steps[0]["of"], 3)

	def test_a_model_api_failure_gets_five_tries(self):
		steps = [
			supervisor.next_step(failed_run(failure_class="model-api", attempt=n)) for n in (1, 2, 3, 4, 5)
		]
		self.assertEqual([s["action"] for s in steps], ["retry"] * 4 + ["stop"])
		self.assertEqual([s["delay"] for s in steps[:4]], [10, 30, 60, 120])

	def test_an_environment_failure_is_retried_once(self):
		first = supervisor.next_step(failed_run(failure_class="env", attempt=1))
		second = supervisor.next_step(failed_run(failure_class="env", attempt=2))
		self.assertEqual((first["action"], first["delay"]), ("retry", 0))
		self.assertEqual(second["action"], "stop")

	def test_a_run_that_is_itself_a_retry_counts_as_the_second_attempt(self):
		self.assertEqual(
			supervisor.next_step(failed_run(failure_class="env", retry_of="DAS-1"))["action"], "stop"
		)

	def test_a_code_failure_goes_back_to_the_agent_for_three_attempts_then_stops(self):
		run = failed_run(failure_class="code", work_item="WI-1")
		for failing_runs, expected in ((1, "return"), (2, "return"), (3, "stop")):
			with patch.object(frappe.db, "count", return_value=failing_runs):
				step = supervisor.next_step(run)
			self.assertEqual((step["action"], step["attempt"], step["of"]), (expected, failing_runs, 3))

	def test_a_gave_up_failure_goes_back_to_the_agent_without_an_attempt_count(self):
		step = supervisor.next_step(failed_run(failure_class="gave-up"))
		self.assertEqual((step["action"], step["of"]), ("return", 1))

	def test_a_policy_failure_stops_and_says_how_to_fix_it(self):
		step = supervisor.next_step(failed_run(failure_class="policy", error_message="403 Forbidden"))
		self.assertEqual(step["action"], "stop")
		self.assertIn("GitHub token in Processa Settings", step["advice"])
		self.assertIn("one_fm", step["advice"])

	def test_a_missing_branch_names_the_branch_to_correct(self):
		step = supervisor.next_step(
			failed_run(failure_class="policy", error_message="couldn't find remote ref WI-9")
		)
		self.assertIn("staging", step["advice"])

	def test_a_class_without_a_policy_goes_back_to_the_agent(self):
		step = supervisor.next_step(failed_run(failure_class="not-reproducible"))
		self.assertEqual((step["action"], step["of"]), ("return", 1))


class TestRecordingTheStep(FrappeTestCase):
	def test_the_attempt_is_a_comment_on_the_work_item(self):
		run = failed_run(failure_class="code", work_item="WI-1")
		work_item = MagicMock()
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value=work_item),
		):
			supervisor.record(
				run, {"action": "return", "attempt": 2, "of": 3, "reason": "code", "delay": 0, "advice": ""}
			)
		work_item.add_comment.assert_called_once_with("Comment", "Attempt 2 of 3, reason: code")

	def test_the_agent_is_told_the_attempt_and_when_there_are_no_more(self):
		run = failed_run(failure_class="code")
		supervisor.record(
			run, {"action": "stop", "attempt": 3, "of": 3, "reason": "code", "delay": 0, "advice": ""}
		)
		self.assertTrue(run.error_message.startswith("Attempt 3 of 3, reason: code."))
		self.assertIn("No more attempts", run.error_message)
		self.assertTrue(run.error_message.endswith("it broke"))

	def test_a_retry_leaves_the_error_alone(self):
		run = failed_run()
		supervisor.record(
			run, {"action": "retry", "attempt": 1, "of": 3, "reason": "infra", "delay": 15, "advice": ""}
		)
		self.assertEqual(run.error_message, "it broke")

	def test_a_single_try_class_leaves_no_attempt_note(self):
		run = failed_run(failure_class="gave-up", work_item="WI-1")
		with patch.object(frappe, "get_doc") as get_doc:
			supervisor.record(
				run,
				{"action": "return", "attempt": 1, "of": 1, "reason": "gave-up", "delay": 0, "advice": ""},
			)
		get_doc.assert_not_called()
		self.assertEqual(run.error_message, "it broke")

	def test_no_comment_is_made_for_a_run_with_no_work_item(self):
		run = failed_run()
		with patch.object(frappe, "get_doc") as get_doc:
			supervisor.record(
				run, {"action": "retry", "attempt": 1, "of": 3, "reason": "infra", "delay": 15, "advice": ""}
			)
		get_doc.assert_not_called()

	def test_the_fix_comes_first_in_the_error(self):
		run = failed_run(failure_class="policy", error_message="403 Forbidden")
		supervisor.record(run, supervisor.next_step(run))
		self.assertTrue(run.error_message.startswith("The GitHub token in Processa Settings"))


class TestTheCallbackFollowsThePolicy(CallbackCase):
	def _result(self, payload: dict, retry_sent: bool = True):
		run = self._run(
			request_payload={"action": "open_pull_request", "args": {}, "agent_name": "Dev Agent"}
		)
		with (
			patch.object(ops, "retry_dispatch", return_value=retry_sent) as retry,
			patch.object(cb, "_enqueue_resume") as resume,
		):
			self._post({"correlation_id": run.name, **payload})
		return frappe.get_doc("Agent Sandbox Run", run.name), retry, resume

	def test_a_pull_request_that_failed_to_open_is_retried_after_a_wait(self):
		_run, retry, resume = self._result({"status": "tests_passed", "pr_error": "GitHub timed out"})
		self.assertEqual(retry.call_args.kwargs["delay"], 15)
		resume.assert_not_called()

	def test_a_retry_that_cannot_be_sent_resumes_the_agent_with_the_failure(self):
		_run, _retry, resume = self._result(
			{"status": "tests_passed", "pr_error": "GitHub timed out"}, retry_sent=False
		)
		resume.assert_called_once()

	def test_a_code_failure_is_not_retried_and_tells_the_agent_the_attempt(self):
		run, retry, resume = self._result({"status": "tests_failed", "failing_tests": ["test_a"]})
		retry.assert_not_called()
		resume.assert_called_once()
		self.assertTrue(run.error_message.startswith("Attempt 1 of 3, reason: code."))

	def test_a_policy_failure_is_not_retried_and_carries_the_fix(self):
		run, retry, resume = self._result({"status": "failed", "error": "403 Forbidden"})
		retry.assert_not_called()
		resume.assert_called_once()
		self.assertIn("GitHub token in Processa Settings", run.error_message)


class TestTheReaperFollowsThePolicy(CallbackCase):
	def _lost(self, attempt: int, retry_sent: bool = True):
		run = self._run(request_payload={"action": "run_tests", "args": {}, "agent_name": "Dev Agent"})
		run.db_set("attempt", attempt, update_modified=False)
		with (
			patch.object(ops, "retry_dispatch", return_value=retry_sent) as retry,
			patch("one_bpmn.api.agent_callback._enqueue_resume") as resume,
		):
			reaper._settle(run, "stale", "No answer for 12 minutes.")
		return run, retry, resume

	def test_a_lost_callback_is_retried_after_a_wait_without_a_person(self):
		_run, retry, resume = self._lost(attempt=1)
		self.assertEqual(retry.call_args.kwargs["delay"], 15)
		resume.assert_not_called()

	def test_a_retry_that_cannot_be_sent_resumes_the_agent(self):
		run, _retry, resume = self._lost(attempt=1, retry_sent=False)
		resume.assert_called_once()
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "resume_enqueued"), 1)

	def test_the_third_lost_callback_resumes_the_agent_and_says_there_are_no_more_attempts(self):
		run, retry, resume = self._lost(attempt=3)
		retry.assert_not_called()
		resume.assert_called_once()
		self.assertIn("No more attempts", frappe.db.get_value("Agent Sandbox Run", run.name, "error_message"))
