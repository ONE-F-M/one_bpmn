"""Bridge between async AI-provider streaming and synchronous Frappe/RQ callers.

Frappe request handlers and RQ workers run synchronously, on threads that do not
own (and generally do not have) an asyncio event loop. Some adapter ``stream()``
methods are ``async def`` generators that yield events inside an event loop.

``iter_stream_sync`` runs the async generator to completion on a dedicated
background thread with its own event loop, and hands each item back to the
calling (sync) thread through a bounded queue. This lets a plain ``for event in
iter_stream_sync(adapter.stream(...)):`` loop consume the stream from ordinary
synchronous code without blocking the whole worker, and without trying (and
failing) to call ``asyncio.run()`` from a thread that might already be inside
a loop.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator, Optional

# Sentinel types passed through the queue between the background asyncio
# thread and the synchronous consumer.


@dataclass
class _Item:
	value: Any


@dataclass
class _Error:
	exc: BaseException


class _Done:
	pass


_DONE = _Done()

# How often the background thread re-checks the stop flag while it is
# waiting for room in the queue.
_PUT_POLL_SECONDS = 0.1


def iter_stream_sync(async_iterable: AsyncIterator[Any], *, queue_maxsize: int = 100) -> Iterator[Any]:
	"""Consume an async iterator (e.g. an adapter's ``stream()`` generator) from
	synchronous code, yielding each item as soon as it is produced.

	Runs the async generator on a private background thread with its own event
	loop, so it never touches (or requires) an event loop on the calling thread.
	If the consumer stops iterating early (e.g. ``break``), the background task
	and its event loop are cancelled and cleaned up.
	"""

	out: "queue.Queue" = queue.Queue(maxsize=queue_maxsize)
	stop_event = threading.Event()

	def _put(item: Any) -> bool:
		"""Put ``item`` on the queue, giving up as soon as the stop flag is set.

		A plain ``out.put(item)`` blocks forever if the queue is full and the
		consumer never drains it again (e.g. it broke out of its loop early).
		Polling with a short timeout lets us notice ``stop_event`` and return
		instead, so the background thread always finishes and ``thread.join()``
		never has to wait past its timeout.
		"""
		while not stop_event.is_set():
			try:
				out.put(item, timeout=_PUT_POLL_SECONDS)
				return True
			except queue.Full:
				continue
		return False

	def _runner() -> None:
		loop = asyncio.new_event_loop()
		try:
			asyncio.set_event_loop(loop)

			async def _pump() -> None:
				try:
					async for item in async_iterable:
						if stop_event.is_set():
							return
						if not _put(_Item(item)):
							return
				except BaseException as exc:  # noqa: BLE001 - propagate to consumer
					_put(_Error(exc))
				else:
					_put(_DONE)

			loop.run_until_complete(_pump())
		finally:
			try:
				# Drain any remaining async generator close/aclose hooks.
				aclose = getattr(async_iterable, "aclose", None)
				if aclose is not None:
					loop.run_until_complete(aclose())
			except Exception:
				pass
			loop.close()

	thread = threading.Thread(target=_runner, name="ai-stream-bridge", daemon=True)
	thread.start()

	try:
		while True:
			item = out.get()
			if isinstance(item, _Item):
				yield item.value
			elif isinstance(item, _Error):
				raise item.exc
			else:  # _Done
				return
	finally:
		# Signal the background pump to stop if the consumer broke out early
		# (e.g. because it hit a tool-call event) and wait for cleanup so we
		# never leak a thread or an open event loop.
		stop_event.set()
		thread.join(timeout=5)


def run_async(coro: "Any") -> Any:
	"""Run a single coroutine to completion from synchronous code.

	Uses a dedicated thread + event loop, same rationale as ``iter_stream_sync``:
	callers may already be inside a Frappe/RQ sync context that has no loop of
	its own, so we never assume ``asyncio.run`` is safe to call directly on the
	current thread.
	"""

	result_box: dict[str, Any] = {}
	error_box: dict[str, BaseException] = {}

	def _runner() -> None:
		loop = asyncio.new_event_loop()
		try:
			asyncio.set_event_loop(loop)
			result_box["value"] = loop.run_until_complete(coro)
		except BaseException as exc:  # noqa: BLE001
			error_box["exc"] = exc
		finally:
			loop.close()

	thread = threading.Thread(target=_runner, name="ai-run-async", daemon=True)
	thread.start()
	thread.join()

	if "exc" in error_box:
		raise error_box["exc"]
	return result_box.get("value")
