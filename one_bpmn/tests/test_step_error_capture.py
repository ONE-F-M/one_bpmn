# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A failed attempt becomes a Step that says what went wrong (WI-002190).

The executor has always built an AttemptRecord for every try that failed,
carrying the error, its tokens and its latency. finalize_ai_run used the
list for one thing: len() as retry_count. So a run knew how many times it
failed and never what went wrong, and zero of roughly 3,000 steps carried
an error while the fields to hold one had existed all along.

Two consequences, both tested here: the error is visible at step level,
and the tokens the failed try burned stop being invisible in the cost.

    bench run-tests --skip-before-tests --module one_bpmn.tests.test_step_error_capture
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import AttemptRecord, ErrorCode, ExecutorResult, TokenUsage
from one_bpmn.agents.observability import finalize_ai_run, record_failed_attempts


class RunFixture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _run(self):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": "error_probe",
				"status": "Running",
				"started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: (
				frappe.db.exists("AI Agent Run", n)
				and frappe.delete_doc("AI Agent Run", n, force=True, ignore_permissions=True)
			)
		)
		return doc

	def _steps(self, run):
		return frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=["step_index", "role", "content", "error_code", "error_message", "latency_ms"],
			order_by="step_index asc",
		)


class TestAFailedAttemptIsVisible(RunFixture):
	def test_the_error_lands_on_the_step(self):
		run = self._run()
		record_failed_attempts(
			run,
			ExecutorResult(
				attempts=[
					AttemptRecord(
						attempt_index=0,
						content="half an answer",
						error_code=ErrorCode.SCHEMA_VALIDATION_FAILED.value,
						error_message="did not match the declared schema",
						latency_ms=1200,
					)
				]
			),
		)
		steps = self._steps(run)
		self.assertEqual(len(steps), 1)
		self.assertEqual(steps[0].error_code, ErrorCode.SCHEMA_VALIDATION_FAILED.value)
		self.assertIn("declared schema", steps[0].error_message)
		self.assertEqual(steps[0].latency_ms, 1200, "the time it wasted is part of the record")

	def test_every_attempt_gets_its_own_step(self):
		run = self._run()
		written = record_failed_attempts(
			run,
			ExecutorResult(
				attempts=[
					AttemptRecord(attempt_index=i, error_code="FAILED_MODEL_CALL", error_message=f"try {i}")
					for i in range(3)
				]
			),
		)
		self.assertEqual(written, 3)
		self.assertEqual([s.step_index for s in self._steps(run)], [1, 2, 3])

	def test_a_run_that_never_failed_writes_nothing(self):
		run = self._run()
		self.assertEqual(record_failed_attempts(run, ExecutorResult(output="fine")), 0)
		self.assertEqual(self._steps(run), [])

	def test_attempts_do_not_collide_with_steps_already_recorded(self):
		"""Indexes continue from what is already there, so a retry recorded
		after a real turn does not overwrite it."""
		from one_bpmn.agents.observability import record_ai_step

		run = self._run()
		record_ai_step(run, 1, "assistant", "the turn that worked")
		record_failed_attempts(
			run, ExecutorResult(attempts=[AttemptRecord(error_code="TIMEOUT", error_message="slow")])
		)
		steps = self._steps(run)
		self.assertEqual([s.step_index for s in steps], [1, 2])
		self.assertEqual(steps[0].error_code, None)
		self.assertEqual(steps[1].error_code, "TIMEOUT")


class TestTheCostStopsHiding(RunFixture):
	def test_a_failed_attempts_tokens_reach_the_run(self):
		"""The tokens a failed try burned were charged by the provider and
		counted nowhere, so every run that retried was undercounted."""
		run = self._run()
		finalize_ai_run(
			run,
			ExecutorResult(
				output="eventually fine",
				attempts=[
					AttemptRecord(
						attempt_index=0,
						error_code="FAILED_MODEL_CALL",
						error_message="boom",
						token_usage=TokenUsage(prompt_tokens=900, completion_tokens=100),
						latency_ms=2500,
					)
				],
			),
		)
		row = frappe.get_doc("AI Agent Run", run.name)
		self.assertEqual(row.retry_count, 1)
		self.assertEqual(row.agent_latency_ms, 2500, "the failed try's time is part of what the run spent")
		steps = self._steps(run)
		self.assertEqual(len(steps), 1)
		self.assertEqual(steps[0].error_code, "FAILED_MODEL_CALL")
