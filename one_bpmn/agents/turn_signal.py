"""Tell a waiting chat request that the worker has finished its turn.

A chat turn runs on the ``bpmn_ai_agent`` worker, so the request that took the
message has to find out when the reply exists. Polling the Chat Message table
alone answers late and costs a query per tick; a one-slot list in the cache
answers the moment the job ends.

The list is the signal, not the payload. The reply is read from the database as
it always was, because the worker and the request are different processes and
the database is the thing they already agree on. A lost signal therefore costs
latency and nothing else: the caller keeps checking the table until its deadline.
"""

from __future__ import annotations

import time

import frappe

_KEY = "bpmn_turn_done:{0}"
# Long enough that a signal published just before a caller starts waiting is
# still there, short enough that an abandoned turn cannot leave rows behind.
_TTL_SECONDS = 600


def _key(instance_name: str) -> str:
	return _KEY.format(instance_name)


def clear(instance_name: str) -> None:
	"""Drop any signal left by an earlier turn on this instance.

	Called before a turn is handed to the worker: a stale signal would end the
	next wait immediately, and the caller would read the previous reply.
	"""
	try:
		frappe.cache().delete_value(_key(instance_name))
	except Exception:
		# The cache is an accelerator here. Losing it degrades to polling.
		pass


def publish(instance_name: str) -> None:
	"""Mark this instance's parked work as finished."""
	try:
		cache = frappe.cache()
		key = _key(instance_name)
		cache.rpush(key, "1")
		cache.expire(cache.make_key(key), _TTL_SECONDS)
	except Exception:
		pass


def wait(instance_name: str, timeout: float, poll_seconds: float = 0.25) -> bool:
	"""Block until the worker signals, or ``timeout`` seconds pass.

	Returns True when a signal arrived. Polls rather than using a blocking pop:
	the cache connection is shared with the rest of the request, and a blocking
	call on it would hold that connection for the whole wait.
	"""
	key = _key(instance_name)
	deadline = time.monotonic() + max(0.0, timeout)
	while True:
		try:
			if frappe.cache().lpop(key):
				return True
		except Exception:
			return False
		if time.monotonic() >= deadline:
			return False
		time.sleep(poll_seconds)
