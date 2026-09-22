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
from contextlib import contextmanager

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
LIVE_TEXT_INSTANCE_FLAG = "bpmn_ai_live_text_instance"
LIVE_TEXT_MASK_FLAG = "bpmn_ai_live_text_masked"
TEXT_EVENT = "TEXT_MESSAGE_CONTENT"


def live_text_sink():
	"""A callable that sends model text to the reader as it is written, or None.

	A turn that runs inside the web request hands the adapter a queue. A turn
	that runs on the worker for a conversation has its instance named on the
	flags by ``live_text_scope``, and its text travels on the same list as the
	tool progress. Text written while a tool runs is masked (``mask_live_text``):
	a tool that calls a model itself writes JSON for the map, not for a person.
	"""
	local_queue = frappe.flags.get(LIVE_TEXT_QUEUE_FLAG)
	if local_queue is not None:

		def sink(delta: str) -> None:
			if delta:
				local_queue.put(delta)

		return sink

	if frappe.flags.get(LIVE_TEXT_MASK_FLAG):
		return None
	instance_name = frappe.flags.get(LIVE_TEXT_INSTANCE_FLAG)
	if not instance_name:
		return None

	# One cache write per delta. Coalesce here if Redis load ever shows it.
	def publish_sink(delta: str) -> None:
		if delta:
			publish_event(instance_name, {"type": TEXT_EVENT, "delta": delta})

	return publish_sink


@contextmanager
def live_text_scope(instance):
	"""Name the instance a chat request is waiting on, for the length of an AI task.

	Only for a conversation: a background agent has nobody reading. Inside a
	masked tool call the scope stays masked, so a sub-agent run as a tool does
	not stream either.
	"""
	name = getattr(instance, "name", None)
	if getattr(instance, "context_doctype", None) != "Chat Conversation" or not name:
		yield
		return
	previous = frappe.flags.get(LIVE_TEXT_INSTANCE_FLAG)
	frappe.flags[LIVE_TEXT_INSTANCE_FLAG] = name
	try:
		yield
	finally:
		frappe.flags[LIVE_TEXT_INSTANCE_FLAG] = previous


@contextmanager
def mask_live_text():
	"""Silence live text while a tool runs."""
	previous = frappe.flags.get(LIVE_TEXT_MASK_FLAG)
	frappe.flags[LIVE_TEXT_MASK_FLAG] = True
	try:
		yield
	finally:
		frappe.flags[LIVE_TEXT_MASK_FLAG] = previous


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
