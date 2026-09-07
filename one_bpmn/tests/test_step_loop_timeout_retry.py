# Copyright (c) 2026, one-fm and contributors
"""aiTimeout/aiMaxRetries used to be read into ExecutorConfig but silently
ignored the moment a call used tools — _run_with_tools routed straight to
run_agent_loop, which called adapter.step() with no timeout and no retry
wrapper at all (confirmed live: the Anthropic adapter passes no timeout to
its own SDK call either). A hung or failing turn in a tool-calling AI Agent
Task therefore ran for however long the provider's own default is, instead
of the configured aiTimeout, and never retried.

Covers: a per-turn timeout aborts that turn's call, a failing/slow call
retries up to max_retries before giving up, and every existing caller
(no timeout_seconds/max_retries passed) is unaffected.
"""

from __future__ import annotations

import asyncio

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, ToolSpec


def _tool(name="noop"):
	return ToolSpec(fn=lambda **kw: "done", name=name, description="d", parameters={}, required=[])


class _SlowThenFast:
	"""First N calls hang past the configured timeout; later calls answer
	immediately — proves a timed-out turn is retried, not treated as fatal."""

	def __init__(self, slow_calls: int, delay: float = 0.2):
		self.slow_calls = slow_calls
		self.delay = delay
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.calls += 1
		if self.calls <= self.slow_calls:
			await asyncio.sleep(self.delay)
		return StepResult(content="done", tool_calls=[])


class _AlwaysSlow:
	def __init__(self, delay: float = 0.2):
		self.delay = delay
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.calls += 1
		await asyncio.sleep(self.delay)
		return StepResult(content="done", tool_calls=[])


class _FailsThenSucceeds:
	"""First N calls raise; proves a raising turn is retried like a timeout."""

	def __init__(self, failures: int):
		self.failures = failures
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.calls += 1
		if self.calls <= self.failures:
			raise ConnectionError("simulated transient failure")
		return StepResult(content="done", tool_calls=[])


def _run(adapter, timeout_seconds=None, max_retries=0, retry_backoff_ms=1):
	return asyncio.run(
		run_agent_loop(
			adapter,
			system="sys",
			user="do the thing",
			tools=[_tool()],
			max_tokens=100,
			max_turns=5,
			timeout_seconds=timeout_seconds,
			max_retries=max_retries,
			retry_backoff_ms=retry_backoff_ms,
		)
	)


class TestStepTimeout(FrappeTestCase):
	def test_a_slow_turn_past_timeout_is_retried_and_can_still_succeed(self):
		adapter = _SlowThenFast(slow_calls=1, delay=0.2)
		completion, suspension = _run(adapter, timeout_seconds=0.05, max_retries=1)
		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "done")
		self.assertEqual(adapter.calls, 2, "one timed-out attempt, then one that answers in time")

	def test_a_persistently_slow_turn_exhausts_retries_and_raises(self):
		adapter = _AlwaysSlow(delay=0.2)
		with self.assertRaises(asyncio.TimeoutError):
			_run(adapter, timeout_seconds=0.05, max_retries=2)
		self.assertEqual(adapter.calls, 3, "the original attempt plus 2 retries, then give up")

	def test_no_timeout_configured_means_unbounded_as_before(self):
		"""timeout_seconds=None (the default for every caller before this
		existed) must never cut off a turn, however long it runs."""
		adapter = _SlowThenFast(slow_calls=1, delay=0.15)
		completion, suspension = _run(adapter, timeout_seconds=None, max_retries=0)
		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "done")
		self.assertEqual(adapter.calls, 1, "no timeout means the slow call itself just completes")


class TestStepRetryOnFailure(FrappeTestCase):
	def test_a_failing_turn_is_retried_up_to_max_retries(self):
		adapter = _FailsThenSucceeds(failures=2)
		completion, suspension = _run(adapter, max_retries=2)
		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "done")
		self.assertEqual(adapter.calls, 3)

	def test_exhausting_retries_on_a_failing_turn_raises_the_original_error(self):
		adapter = _FailsThenSucceeds(failures=5)
		with self.assertRaises(ConnectionError):
			_run(adapter, max_retries=2)
		self.assertEqual(adapter.calls, 3, "the original attempt plus 2 retries, then give up")

	def test_zero_retries_is_the_default_and_fails_on_the_first_error(self):
		adapter = _FailsThenSucceeds(failures=1)
		with self.assertRaises(ConnectionError):
			_run(adapter)
		self.assertEqual(adapter.calls, 1)
