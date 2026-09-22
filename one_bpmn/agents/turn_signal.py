"""Carry a turn's progress from the worker back to the request waiting on it.

A chat turn runs on the ``bpmn_ai_agent`` worker, so the request that took the
message has to learn two things from another process: that the turn finished,
and what it is doing while it has not. Both travel on one list in the cache,
oldest first, and the last entry is always the end marker.

The list carries progress, never the answer. The reply is read from the
database, because that is the thing both processes already agree on, so a lost
entry costs a status line or some latency and never a reply.
"""

from __future__ import annotations

import json
import time

import frappe

_KEY = "bpmn_turn_events:{0}"
# Long enough that an entry published just before a caller starts reading is
# still there, short enough that an abandoned turn cannot leave rows behind.
_TTL_SECONDS = 600
_DONE = "done"


def _key(instance_name: str) -> str:
	return _KEY.format(instance_name)


def clear(instance_name: str) -> None:
	"""Drop whatever an earlier turn on this instance left behind.

	Called before a turn is handed to the worker: a stale end marker would stop
	the next wait immediately and the caller would read the previous reply.
	"""
	try:
		frappe.cache().delete_value(_key(instance_name))
	except Exception:
		# The cache is an accelerator here. Losing it degrades to a plain wait.
		pass


def publish_event(instance_name: str, event: dict) -> None:
	"""Put one progress event on the turn's list."""
	_push(instance_name, event)


def publish(instance_name: str) -> None:
	"""Mark this instance's parked work as finished."""
	_push(instance_name, {"type": _DONE})


def _push(instance_name: str, payload: dict) -> None:
	try:
		cache = frappe.cache()
		key = _key(instance_name)
		cache.rpush(key, json.dumps(payload, default=str))
		cache.expire(cache.make_key(key), _TTL_SECONDS)
	except Exception:
		pass


def consume(instance_name: str, timeout: float, poll_seconds: float = 0.25):
	"""Yield this turn's progress events until it ends or ``timeout`` passes.

	The end marker is consumed and not yielded, so a caller can simply iterate
	and then read the reply. Polls rather than using a blocking pop, because the
	cache connection is shared with the rest of the request and a blocking call
	would hold it for the whole turn.
	"""
	key = _key(instance_name)
	deadline = time.monotonic() + max(0.0, timeout)
	while True:
		try:
			raw = frappe.cache().lpop(key)
		except Exception:
			return
		if raw is None:
			if time.monotonic() >= deadline:
				return
			time.sleep(poll_seconds)
			continue
		try:
			event = json.loads(raw)
		except (TypeError, ValueError):
			continue
		if event.get("type") == _DONE:
			return
		yield event


LIVE_TEXT_QUEUE_FLAG = "bpmn_ai_live_text_queue"

def live_text_sink():
	"""A callable that sends model text to the reader as it is written, or None.

	Only a turn that runs inside the web request gets one: there the model's
	text is the reply, word for word, and the request hands the adapter a
	queue to put it on. A map-driven turn gets none. Its model calls include
	sub-agents whose text is machine-shaped for the map to read, and the
	reply the person sees is composed afterwards, so forwarding the raw text
	would show them the wrong thing.
	"""
	local_queue = frappe.flags.get(LIVE_TEXT_QUEUE_FLAG)
	if local_queue is None:
		return None

	def sink(delta: str) -> None:
		if delta:
			local_queue.put(delta)

	return sink


def wait(instance_name: str, timeout: float, poll_seconds: float = 0.25) -> bool:
	"""Block until the turn ends, or ``timeout`` passes.

	Returns True when the end marker arrived. Progress events are dropped on the
	way past: a caller that only wants the reply has nowhere to put them. The
	pop loop is written out again rather than reusing ``consume``, because a
	generator that stops for two different reasons cannot tell the caller which
	one it was.
	"""
	key = _key(instance_name)
	deadline = time.monotonic() + max(0.0, timeout)
	while True:
		try:
			raw = frappe.cache().lpop(key)
		except Exception:
			return False
		if raw is None:
			if time.monotonic() >= deadline:
				return False
			time.sleep(poll_seconds)
			continue
		try:
			if json.loads(raw).get("type") == _DONE:
				return True
		except (TypeError, ValueError):
			continue
