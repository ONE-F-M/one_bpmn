"""Carry a turn's progress from the worker back to the request waiting on it."""

from __future__ import annotations

import json
import math
import time
from contextlib import contextmanager

import frappe
from frappe.utils import cint

_KEY = "bpmn_turn_events:{0}"
_TTL_SECONDS = 600
_DONE = "done"


def _key(instance_name: str) -> str:
	return _KEY.format(instance_name)


def clear(instance_name: str) -> None:
	"""Drop whatever an earlier turn on this instance left behind."""
	try:
		frappe.cache().delete_value(_key(instance_name))
	except Exception:
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


STILL_WORKING_EVENT = "onefm.turn_progress"
PROGRESS_EVENT = "onefm.progress"
PROGRESS_HEARTBEAT_SECONDS = 25
_AI_QUEUE = "bpmn_ai_agent"


def publish_progress(message: str, phase: int = 0, total: int = 0) -> None:
	"""Tell the person waiting on this chat turn what the worker is doing now, as a progress line."""
	instance_name = frappe.flags.get(LIVE_TEXT_INSTANCE_FLAG)
	if instance_name:
		value = {"phase": cint(phase), "total": cint(total), "message": message}
		publish_event(instance_name, {"type": "CUSTOM", "name": PROGRESS_EVENT, "value": value})


def consume(instance_name: str, timeout: float, idle_seconds: float | None = None, still_running=None):
	"""Yield this turn's progress events until it ends or ``timeout`` passes; the end marker is not yielded."""
	key = _key(instance_name)
	deadline = time.monotonic() + max(0.0, timeout)
	progress, progress_at = None, 0.0
	while True:
		quiet = idle_seconds
		if progress and idle_seconds is not None:
			quiet = min(idle_seconds, PROGRESS_HEARTBEAT_SECONDS)
		window = deadline if quiet is None else min(deadline, time.monotonic() + quiet)
		try:
			raw = _pop_before(key, window)
		except Exception:
			return
		if raw is None:
			if still_running and time.monotonic() < deadline and still_running():
				yield _quiet_event(progress, time.monotonic() - progress_at)
				continue
			return
		try:
			event = json.loads(raw)
		except (TypeError, ValueError):
			continue
		if event.get("type") == _DONE:
			return
		if event.get("name") == PROGRESS_EVENT:
			progress, progress_at = event.get("value") or {}, time.monotonic()
		yield event


def _quiet_event(progress: dict | None, seconds: float) -> dict:
	"""The event for a quiet stretch: the last progress line with the time spent, else the general still-
	working note."""
	if progress:
		message = frappe._("{0} (still working, {1}s)").format(progress.get("message") or "", int(seconds))
		return {"type": "CUSTOM", "name": PROGRESS_EVENT, "value": {**progress, "message": message}}
	return {
		"type": "CUSTOM",
		"name": STILL_WORKING_EVENT,
		"value": {"text": frappe._("Still working on your last message…")},
	}


LIVE_TEXT_QUEUE_FLAG = "bpmn_ai_live_text_queue"
LIVE_TEXT_INSTANCE_FLAG = "bpmn_ai_live_text_instance"
LIVE_TEXT_MASK_FLAG = "bpmn_ai_live_text_masked"
TEXT_EVENT = "TEXT_MESSAGE_CONTENT"


def live_text_sink():
	"""A callable that sends model text to the reader as it is written, or None."""
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

	def publish_sink(delta: str) -> None:
		if delta:
			publish_event(instance_name, {"type": TEXT_EVENT, "delta": delta})

	return publish_sink


@contextmanager
def live_text_scope(instance):
	"""Name the instance a chat request is waiting on, for the length of an AI task."""
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


def wait(instance_name: str, timeout: float) -> bool:
	"""Block until the turn ends, or ``timeout`` passes."""
	key = _key(instance_name)
	deadline = time.monotonic() + max(0.0, timeout)
	while True:
		try:
			raw = _pop_before(key, deadline)
		except Exception:
			return False
		if raw is None:
			return False
		try:
			if json.loads(raw).get("type") == _DONE:
				return True
		except (TypeError, ValueError):
			continue


def _pop_before(key: str, deadline: float) -> bytes | None:
	"""Block on the turn's list until an entry arrives or ``deadline`` passes."""
	remaining = deadline - time.monotonic()
	if remaining <= 0:
		return None
	cache = frappe.cache()
	popped = cache.blpop(cache.make_key(key), timeout=math.ceil(remaining * 1000) / 1000)
	return popped[1] if popped else None


def ai_job_running(instance_name: str) -> bool:
	"""Is an AI job for this instance queued or running on the worker?"""
	from frappe.utils.background_jobs import create_job_id, get_queue, get_running_jobs_in_queue

	from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_QUEUES

	prefix = create_job_id(f"bpmn-ai-{instance_name}-")
	for queue_name in AI_AGENT_QUEUES:
		queue = get_queue(queue_name)
		if any(job.id.startswith(prefix) for job in [*queue.jobs, *get_running_jobs_in_queue(queue)]):
			return True
	return False
