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

	def _make_instance(self):
		"""A real BPMN Process Instance to link runs to.

		AI Agent Run.instance is a validated Link, so the fake names these tests
		used ("inst", "test-instance") made create_ai_run fall back to its stub
		and every downstream assertion see None. Cached per test-class run so the
		model/instance pair is only built once.
		"""
		if getattr(self.__class__, "_instance_name", None):
			return self.__class__._instance_name

		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"test-model-{frappe.generate_hash(length=8)}",
			"process_id": f"test_proc_{frappe.generate_hash(length=8)}",
			"version": 1,
		})
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True)

		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": model.name,
			"status": "Active",
		}).insert(ignore_permissions=True)
		self.__class__._instance_name = instance.name
		return instance.name

	def _make_provider(self):
		"""An enabled AI Provider Credentials record to hang pricing off.

		Created per test rather than assuming a fixture name exists — these
		tests previously hard-coded provider="openai", which does not exist on
		every site and made the whole module fail at setup.
		"""
		name = f"test-provider-{frappe.generate_hash(length=8)}"
		frappe.get_doc({
			"doctype": "AI Provider Credentials",
			"provider_name": name,
			"provider_type": "OpenAI",
			"api_key": "test-key-not-used",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		return name

	def _make_pricing(self, model, input_cost_per_1k, output_cost_per_1k, **cache_rates):
		"""Create an active AI Model Pricing record for *model*."""
		row = {
			"doctype": "AI Model Pricing",
			"model_name": model,
			"provider": self._make_provider(),
			"input_cost_per_1k": input_cost_per_1k,
			"output_cost_per_1k": output_cost_per_1k,
			"effective_from": "2025-01-01",
			"is_active": 1,
		}
		row.update(cache_rates)
		doc = frappe.get_doc(row)
		doc.insert(ignore_permissions=True)
		return doc

	def test_create_ai_run_creates_record(self):
		"""create_ai_run() creates an AI Agent Run with status='Running'."""
		from one_bpmn.agents.observability import create_ai_run

		config = self._make_config()
		instance = frappe._dict({"name": self._make_instance()})
		run = create_ai_run(instance, "Activity_Test", "task", config)

		self.assertTrue(frappe.db.exists("AI Agent Run", run.name))
		self.assertEqual(run.status, "Running")
		self.assertEqual(run.instance, instance.name)
		self.assertEqual(run.bpmn_id, "Activity_Test")
		self.assertEqual(run.model, "gpt-4o")

	def test_record_ai_step_creates_step(self):
		"""record_ai_step() creates an AI Agent Step linked to the Run."""
		from one_bpmn.agents.observability import create_ai_run, record_ai_step

		config = self._make_config()
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		run = create_ai_run(frappe._dict({"name": self._make_instance()}), "A1", "task", config)

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
		instance = frappe._dict({"name": self._make_instance()})

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

	# ── WI-001643: cache-aware cost + latency that excludes human wait ──

	def _priced_run(self, **rates):
		"""A Running AI Agent Run whose model has pricing."""
		from one_bpmn.agents.observability import create_ai_run

		model = f"priced-{frappe.generate_hash(length=6)}"
		self._make_pricing(
			model,
			rates.get("input_rate", 0.01),
			rates.get("output_rate", 0.03),
			cache_read_cost_per_1k=rates.get("cache_read", 0.001),
			cache_write_cost_per_1k=rates.get("cache_write", 0.0125),
		)
		return create_ai_run(
			frappe._dict({"name": self._make_instance()}), "A1", "task", self._make_config(model=model)
		)

	def test_record_ai_step_splits_cache_cost(self):
		"""A step's prompt is costed across uncached / cache-read / cache-write."""
		from one_bpmn.agents.observability import record_ai_step

		run = self._priced_run()
		step = record_ai_step(
			run, 0, "assistant", "response",
			prompt_tokens=10_000,       # inclusive of the two below
			cache_read_tokens=6_000,
			cache_write_tokens=1_000,
			completion_tokens=2_000,
		)
		self.assertIsNotNone(step)
		self.assertEqual(step.cache_read_tokens, 6_000)
		self.assertEqual(step.cache_write_tokens, 1_000)
		# 3k uncached @0.01, 6k read @0.001, 1k write @0.0125, 2k out @0.03
		self.assertAlmostEqual(step.input_cost, 0.03, places=6)
		self.assertAlmostEqual(step.cache_read_cost, 0.006, places=6)
		self.assertAlmostEqual(step.cache_write_cost, 0.0125, places=6)
		self.assertAlmostEqual(step.output_cost, 0.06, places=6)
		self.assertAlmostEqual(step.cost, 0.1085, places=6)

	def test_record_ai_step_without_cache_bills_whole_prompt_at_input_rate(self):
		"""Backward compatibility: no cache tokens → unchanged cost."""
		from one_bpmn.agents.observability import record_ai_step

		run = self._priced_run()
		step = record_ai_step(
			run, 0, "assistant", "r", prompt_tokens=1_000, completion_tokens=1_000
		)
		self.assertAlmostEqual(step.input_cost, 0.01, places=6)
		self.assertAlmostEqual(step.cost, 0.04, places=6)
		self.assertEqual(step.cache_read_tokens, 0)
		self.assertEqual(step.cache_write_cost, 0.0)

	def test_finalize_rolls_up_cache_tokens_and_costs(self):
		"""Run totals include the cache breakdown summed across steps."""
		from one_bpmn.agents.observability import record_ai_step, finalize_ai_run

		run = self._priced_run()
		for i in range(2):
			record_ai_step(
				run, i, "assistant", "r",
				prompt_tokens=5_000, cache_read_tokens=4_000,
				cache_write_tokens=500, completion_tokens=1_000,
			)
		finalize_ai_run(run, ExecutorResult(
			output="done",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(
				prompt_tokens=10_000, completion_tokens=2_000, total_tokens=12_000,
				cache_read_tokens=8_000, cache_write_tokens=1_000,
			),
		))
		run.reload()
		self.assertEqual(run.total_cache_read_tokens, 8_000)
		self.assertEqual(run.total_cache_write_tokens, 1_000)
		# per step: 500 uncached @0.01 = 0.005; 4k read @0.001 = 0.004;
		#           500 write @0.0125 = 0.00625; 1k out @0.03 = 0.03
		self.assertAlmostEqual(run.total_cache_read_cost, 0.008, places=6)
		self.assertAlmostEqual(run.total_cache_write_cost, 0.0125, places=6)
		self.assertAlmostEqual(run.total_input_cost, 0.01, places=6)
		self.assertAlmostEqual(run.estimated_cost, 2 * 0.04525, places=6)

	def test_agent_latency_is_step_time_not_wall_clock(self):
		"""agent_latency_ms measures work done, so it excludes idle wall-clock.

		This is the metric A/B experiments need: a run parked for a person has a
		huge duration_ms but the same agent latency as one that was not.
		"""
		import datetime
		from one_bpmn.agents.observability import record_ai_step, finalize_ai_run

		run = self._priced_run()
		# Pretend the run began an hour ago (a human sat on it).
		run.db_set("started_at", now_datetime() - datetime.timedelta(hours=1))
		record_ai_step(run, 0, "assistant", "r", latency_ms=200)
		record_ai_step(run, 1, "assistant", "r", latency_ms=300)

		finalize_ai_run(run, ExecutorResult(output="ok", error_code=ErrorCode.SUCCESS))
		run.reload()
		self.assertEqual(run.agent_latency_ms, 500)
		self.assertGreater(run.duration_ms, 60 * 60 * 1000 - 5_000)
		self.assertLess(run.agent_latency_ms, run.duration_ms)

	def test_agent_latency_recorded_on_error_too(self):
		"""A failed run still spent real time; the metric must not be lost."""
		from one_bpmn.agents.observability import record_ai_step, finalize_ai_run

		run = self._priced_run()
		record_ai_step(run, 0, "assistant", "r", latency_ms=120)
		finalize_ai_run(run, ExecutorResult(
			error_code=ErrorCode.FAILED_MODEL_CALL, error_message="boom",
		))
		run.reload()
		self.assertEqual(run.status, "Error")
		self.assertEqual(run.agent_latency_ms, 120)
