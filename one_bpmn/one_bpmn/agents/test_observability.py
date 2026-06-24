"""
Tests for the AI Agent observability instrumentation layer.

Covers create_ai_run, record_ai_step, finalize_ai_run, and
finalize_ai_run_on_exception — all with mocked executors.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorResult


class TestObservability(FrappeTestCase):

	def _make_config(self, **kwargs) -> ExecutorConfig:
		defaults = {
			"backend": "direct_api",
			"provider_name": "",
			"model": "gpt-4o",
			"system_prompt": "You are a helpful assistant.",
			"user_prompt": "Say hello.",
		}
		defaults.update(kwargs)
		return ExecutorConfig(**defaults)

	def test_create_ai_run_creates_record(self):
		"""create_ai_run() creates an AI Agent Run with status='Running'."""
		from one_bpmn.agents.observability import create_ai_run

		config = self._make_config()
		instance = frappe._dict({"name": "test-instance"})
		run = create_ai_run(instance, "Activity_Test", "task", config)

		self.assertTrue(frappe.db.exists("AI Agent Run", run.name))
		self.assertEqual(run.status, "Running")
		self.assertEqual(run.instance, "test-instance")
		self.assertEqual(run.bpmn_id, "Activity_Test")
		self.assertEqual(run.model, "gpt-4o")

	def test_record_ai_step_creates_step(self):
		"""record_ai_step() creates an AI Agent Step linked to the Run."""
		from one_bpmn.agents.observability import create_ai_run, record_ai_step

		config = self._make_config()
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		step = record_ai_step(run, 0, "system", "System prompt here")
		self.assertIsNotNone(step)
		self.assertEqual(step.role, "system")
		self.assertEqual(step.step_index, 0)

	def test_finalize_ai_run_success(self):
		"""finalize_ai_run() with SUCCESS sets status='Success', computes duration."""
		from one_bpmn.agents.observability import create_ai_run, finalize_ai_run

		config = self._make_config()
		# Simulate a run that started 1 second ago
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		# Speed: cheat by setting started_at to 1s ago
		import datetime
		run.db_set("started_at", now_datetime() - datetime.timedelta(seconds=1))

		result = ExecutorResult(
			output="Hello!",
			error_code=ErrorCode.SUCCESS,
		)
		finalize_ai_run(run, result)

		run.reload()
		self.assertEqual(run.status, "Success")
		self.assertIsNotNone(run.ended_at)
		self.assertGreater(run.duration_ms, 0)

	def test_finalize_ai_run_error(self):
		"""finalize_ai_run() with error sets status='Error' and stores error_code."""
		from one_bpmn.agents.observability import create_ai_run, finalize_ai_run

		config = self._make_config()
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		result = ExecutorResult(
			output=None,
			error_code=ErrorCode.FAILED_MODEL_CALL,
			error_message="Model timed out",
		)
		finalize_ai_run(run, result)

		run.reload()
		self.assertEqual(run.status, "Error")
		self.assertEqual(run.error_code, "FAILED_MODEL_CALL")
		self.assertEqual(run.error_message, "Model timed out")

	def test_finalize_ai_run_on_exception(self):
		"""finalize_ai_run_on_exception() sets error_code='UNEXPECTED_ERROR'."""
		from one_bpmn.agents.observability import (
			create_ai_run,
			finalize_ai_run_on_exception,
		)

		config = self._make_config()
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		finalize_ai_run_on_exception(run, RuntimeError("Something went wrong"))

		run.reload()
		self.assertEqual(run.status, "Error")
		self.assertEqual(run.error_code, "UNEXPECTED_ERROR")
		self.assertIn("Something went wrong", run.error_message)

	def test_cost_zero_when_no_pricing(self):
		"""When no AI Model Pricing exists for the model, step cost is 0."""
		from one_bpmn.agents.observability import create_ai_run, record_ai_step

		config = self._make_config(model="invented-model-no-pricing")
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		step = record_ai_step(
			run, 0, "user", "test",
			prompt_tokens=100,
			completion_tokens=50,
		)
		self.assertIsNotNone(step)
		self.assertEqual(step.cost, 0)

	def test_create_ai_run_db_error_caught(self):
		"""When create_ai_run itself throws, it is caught and logged."""
		from one_bpmn.agents.observability import create_ai_run

		config = self._make_config()
		# Pass None instance to cause DB error
		run = create_ai_run(None, "A1", "task", config)
		self.assertTrue(getattr(run, "stub", False))
