"""
Tests for the AI Agent observability instrumentation layer.

Covers create_ai_run, record_ai_step, finalize_ai_run, and
finalize_ai_run_on_exception — all with mocked executors.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorResult, TokenUsage


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

	def _make_pricing(self, model, input_cost_per_1k, output_cost_per_1k):
		"""Create an active AI Model Pricing record for *model*."""
		doc = frappe.get_doc({
			"doctype": "AI Model Pricing",
			"model_name": model,
			"provider": "openai",
			"input_cost_per_1k": input_cost_per_1k,
			"output_cost_per_1k": output_cost_per_1k,
			"effective_from": "2025-01-01",
			"is_active": 1,
		})
		doc.insert(ignore_permissions=True)
		return doc

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
		# Step is linked to the run
		self.assertEqual(step.run, run.name)

	def test_record_ai_step_computes_cost(self):
		"""record_ai_step() computes cost from AI Model Pricing for the run's model."""
		from one_bpmn.agents.observability import create_ai_run, record_ai_step

		model = f"priced-{frappe.generate_hash(length=6)}"
		self._make_pricing(model, input_cost_per_1k=0.01, output_cost_per_1k=0.03)

		config = self._make_config(model=model)
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		step = record_ai_step(
			run, 0, "assistant", "response",
			prompt_tokens=1000,
			completion_tokens=2000,
		)
		# (1000/1000)*0.01 + (2000/1000)*0.03 = 0.01 + 0.06 = 0.07
		self.assertIsNotNone(step)
		self.assertAlmostEqual(step.cost, 0.07, places=6)

	def test_record_ai_step_stores_latency_ms(self):
		"""record_ai_step() stores the latency_ms value on the step."""
		from one_bpmn.agents.observability import create_ai_run, record_ai_step

		config = self._make_config()
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		step = record_ai_step(run, 0, "assistant", "response", latency_ms=350)
		self.assertIsNotNone(step)
		self.assertEqual(step.latency_ms, 350)

	def test_finalize_ai_run_success(self):
		"""finalize_ai_run() with SUCCESS sets status, duration, token totals, and cost."""
		from one_bpmn.agents.observability import (
			create_ai_run,
			record_ai_step,
			finalize_ai_run,
		)

		model = f"priced-{frappe.generate_hash(length=6)}"
		self._make_pricing(model, input_cost_per_1k=0.01, output_cost_per_1k=0.03)

		config = self._make_config(model=model)
		# Simulate a run that started 1 second ago
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		# Speed: cheat by setting started_at to 1s ago
		import datetime
		run.db_set("started_at", now_datetime() - datetime.timedelta(seconds=1))

		# Record one assistant step so there is a cost to sum.
		# cost = (1000/1000)*0.01 + (500/1000)*0.03 = 0.01 + 0.015 = 0.025
		record_ai_step(
			run, 0, "assistant", "response",
			prompt_tokens=1000,
			completion_tokens=500,
		)

		result = ExecutorResult(
			output="Hello!",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
		)
		finalize_ai_run(run, result)

		run.reload()
		self.assertEqual(run.status, "Success")
		self.assertIsNotNone(run.ended_at)
		self.assertGreater(run.duration_ms, 0)
		# Token totals are summed from the result
		self.assertEqual(run.total_prompt_tokens, 1000)
		self.assertEqual(run.total_completion_tokens, 500)
		self.assertEqual(run.total_tokens, 1500)
		# estimated_cost is summed from the step costs
		self.assertAlmostEqual(run.estimated_cost, 0.025, places=6)

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
		"""No AI Model Pricing → step cost 0 and run estimated_cost 0 (no error)."""
		from one_bpmn.agents.observability import (
			create_ai_run,
			record_ai_step,
			finalize_ai_run,
		)

		config = self._make_config(model="invented-model-no-pricing")
		run = create_ai_run(frappe._dict({"name": "inst"}), "A1", "task", config)

		step = record_ai_step(
			run, 0, "user", "test",
			prompt_tokens=100,
			completion_tokens=50,
		)
		self.assertIsNotNone(step)
		self.assertEqual(step.cost, 0)

		result = ExecutorResult(
			output="ok",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
		)
		finalize_ai_run(run, result)

		run.reload()
		self.assertEqual(run.status, "Success")
		self.assertEqual(run.estimated_cost, 0)

	def test_create_ai_run_db_error_caught(self):
		"""When inserting the Run throws a DB error, it is caught and logged — no exception propagates."""
		from unittest.mock import patch
		from frappe.model.document import Document
		from one_bpmn.agents.observability import create_ai_run

		config = self._make_config()
		instance = frappe._dict({"name": "inst"})

		# Simulate a database failure during run.insert()
		with patch("frappe.log_error") as mock_log, \
			patch.object(Document, "insert", side_effect=Exception("simulated DB error")):
			run = create_ai_run(instance, "A1", "task", config)

		# No exception propagated; a stub is returned and the failure was logged
		self.assertTrue(getattr(run, "stub", False))
		self.assertTrue(mock_log.called)

	def test_finalize_ai_run_none_run_is_noop(self):
		"""finalize_ai_run(None, result) returns silently — no crash."""
		from one_bpmn.agents.observability import finalize_ai_run

		result = ExecutorResult(
			output="Hello!",
			error_code=ErrorCode.SUCCESS,
		)
		# Must not raise
		finalize_ai_run(None, result)

	def test_finalize_ai_run_on_exception_none_run_is_noop(self):
		"""finalize_ai_run_on_exception(None, exc) returns silently — no crash."""
		from one_bpmn.agents.observability import finalize_ai_run_on_exception

		# Must not raise
		finalize_ai_run_on_exception(None, RuntimeError("test"))
