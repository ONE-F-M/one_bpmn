# Copyright (c) 2026, one-fm and contributors
# Regression coverage for one_bpmn.agents.async_bridge, the helper that lets
# synchronous Frappe/RQ code consume an async generator or coroutine without
# an event loop of its own.

from __future__ import annotations

import threading
import time
import unittest

from one_bpmn.agents.async_bridge import iter_stream_sync, run_async


async def _gen(items):
	for item in items:
		yield item


async def _gen_then_raise(items, exc):
	for item in items:
		yield item
	raise exc


def _active_bridge_threads():
	return [t for t in threading.enumerate() if t.name in ("ai-stream-bridge", "ai-run-async")]


class TestIterStreamSync(unittest.TestCase):
	def test_every_item_reaches_the_caller_in_order(self):
		out = list(iter_stream_sync(_gen([1, 2, 3, 4, 5])))
		self.assertEqual(out, [1, 2, 3, 4, 5])

	def test_exception_inside_the_generator_reaches_the_caller(self):
		with self.assertRaises(ValueError):
			list(iter_stream_sync(_gen_then_raise([1, 2], ValueError("boom"))))

	def test_breaking_out_early_leaves_no_thread_behind(self):
		collected = []
		for item in iter_stream_sync(_gen(range(50)), queue_maxsize=1):
			collected.append(item)
			if len(collected) == 2:
				break

		# Give the background thread a brief moment to actually finish; the
		# generator itself must not still be alive after that.
		deadline = time.monotonic() + 2
		while _active_bridge_threads() and time.monotonic() < deadline:
			time.sleep(0.05)

		self.assertEqual(collected[:2], [0, 1])
		self.assertEqual(_active_bridge_threads(), [])


class TestRunAsync(unittest.TestCase):
	def test_returns_the_coroutine_result(self):
		async def _coro():
			return 42

		self.assertEqual(run_async(_coro()), 42)

	def test_propagates_a_raised_error(self):
		async def _coro():
			raise RuntimeError("nope")

		with self.assertRaises(RuntimeError):
			run_async(_coro())


if __name__ == "__main__":
	unittest.main()
