# Copyright (c) 2026, one-fm and contributors
"""A model call that fails for a passing reason is waited out; one the provider rejected is not retried."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import step_loop


class ProviderError(Exception):
	def __init__(self, status_code=None, retry_after=None):
		super().__init__(f"status {status_code}")
		self.status_code = status_code
		self.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})


class Adapter:
	def __init__(self, *outcomes):
		self.outcomes = list(outcomes)
		self.calls = 0

	async def step(self, *args, **kwargs):
		self.calls += 1
		outcome = self.outcomes.pop(0)
		if isinstance(outcome, BaseException):
			raise outcome
		return outcome


def _run(adapter, **kwargs):
	waits = []

	async def fake_sleep(seconds):
		waits.append(seconds)

	with patch.object(step_loop.asyncio, "sleep", fake_sleep), patch.object(step_loop.random, "uniform", return_value=0):
		result = asyncio.run(step_loop._step_with_retries(adapter, "sys", [], None, 100, **kwargs))
	return result, waits


class TestStepRetries(FrappeTestCase):
	def test_an_overload_is_retried_up_to_the_configured_limit_with_growing_waits(self):
		adapter = Adapter(*[ProviderError(529)] * 4, "ok")
		result, waits = _run(adapter, max_retries=4, retry_backoff_ms=1000)
		self.assertEqual(result, "ok")
		self.assertEqual(adapter.calls, 5)
		self.assertEqual(waits, [1.0, 2.0, 4.0, 8.0])

	def test_a_rate_limit_waits_as_long_as_the_provider_asks(self):
		adapter = Adapter(ProviderError(429, retry_after="7"), "ok")
		_result, waits = _run(adapter, max_retries=2)
		self.assertEqual(waits, [7.0])

	def test_a_long_retry_after_is_capped(self):
		adapter = Adapter(ProviderError(429, retry_after="900"), "ok")
		_result, waits = _run(adapter, max_retries=2)
		self.assertEqual(waits, [step_loop.MAX_BACKOFF_SECONDS])

	def test_the_backoff_is_capped(self):
		adapter = Adapter(*[ProviderError(503)] * 4, "ok")
		_result, waits = _run(adapter, max_retries=6, retry_backoff_ms=20000)
		self.assertEqual(max(waits), step_loop.MAX_BACKOFF_SECONDS)
		self.assertTrue(all(w <= step_loop.MAX_BACKOFF_SECONDS for w in waits))

	def test_a_rejected_request_is_not_retried_at_all(self):
		for status in (400, 401, 403, 404, 413, 422):
			adapter = Adapter(ProviderError(status), "never")
			with self.assertRaises(ProviderError):
				_run(adapter, max_retries=5)
			self.assertEqual(adapter.calls, 1, status)

	def test_zero_retries_means_none_even_for_an_overload(self):
		adapter = Adapter(ProviderError(529), "never")
		with self.assertRaises(ProviderError):
			_run(adapter, max_retries=0)
		self.assertEqual(adapter.calls, 1)

	def test_a_failure_that_says_nothing_keeps_the_configured_retries_only(self):
		adapter = Adapter(RuntimeError("odd"), RuntimeError("odd"), "ok")
		result, _waits = _run(adapter, max_retries=2)
		self.assertEqual((result, adapter.calls), ("ok", 3))
		adapter = Adapter(RuntimeError("odd"), RuntimeError("odd"), "never")
		with self.assertRaises(RuntimeError):
			_run(adapter, max_retries=1)
		self.assertEqual(adapter.calls, 2)

	def test_a_failure_that_never_clears_raises_after_the_limit(self):
		adapter = Adapter(*[ProviderError(500)] * 6)
		with self.assertRaises(ProviderError):
			_run(adapter, max_retries=3)
		self.assertEqual(adapter.calls, 4)

	def test_a_timeout_or_a_dropped_connection_is_retried_within_the_limit(self):
		for error in (asyncio.TimeoutError(), ConnectionError("reset")):
			adapter = Adapter(error, "ok")
			result, _ = _run(adapter, max_retries=1)
			self.assertEqual((result, adapter.calls), ("ok", 2))

	def test_a_truncated_answer_is_never_retried(self):
		adapter = Adapter(step_loop.LLMTruncatedError("cut"), "never")
		with self.assertRaises(step_loop.LLMTruncatedError):
			_run(adapter, max_retries=5)
		self.assertEqual(adapter.calls, 1)

	def test_a_success_needs_no_wait(self):
		result, waits = _run(Adapter("ok"), max_retries=3)
		self.assertEqual((result, waits), ("ok", []))

	def test_the_status_may_sit_on_the_response(self):
		error = Exception("x")
		error.response = SimpleNamespace(status_code=401, headers={})
		adapter = Adapter(error, "never")
		with self.assertRaises(Exception):
			_run(adapter, max_retries=5)
		self.assertEqual(adapter.calls, 1)
