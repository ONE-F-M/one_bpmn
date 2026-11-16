# Copyright (c) 2026, one-fm and contributors
"""Per-turn scratch store shared by an AI Agent Task's stage tools."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars

import frappe


def _key(conversation: str) -> str:
	return f"ait_turn:{conversation}"


def get_turn(conversation: str) -> dict:
	"""Return the current turn scratch dict (empty dict if none)."""
	key = _key(conversation)
	frappe.local.cache.pop(frappe.cache.make_key(key), None)
	return frappe.cache.get_value(key) or {}


def set_turn(conversation: str, data: dict) -> None:
	frappe.cache.set_value(_key(conversation), data)


_TERMINAL_KEYS = ("output", "done")

TURN_ANSWERED_FLAG = "bpmn_turn_answered"


def update_turn(conversation: str, **kwargs) -> dict:
	"""Merge ``kwargs`` into the turn scratch and persist it. Returns the result."""
	turn = get_turn(conversation)
	if turn.get("done") and any(k in kwargs for k in _TERMINAL_KEYS):
		_existing = turn.get("output")
		_kept = _existing.get("intent") if isinstance(_existing, dict) else None
		_attempted = kwargs.get("output")
		_dropped = _attempted.get("intent") if isinstance(_attempted, dict) else None
		frappe.logger("processa").warning(
			f"turn_state: refused a second terminal write on conversation {conversation} "
			f"- kept intent={_kept!r}, dropped intent={_dropped!r}. A stage tool ran "
			f"after the turn was already answered."
		)
		kwargs = {k: v for k, v in kwargs.items() if k not in _TERMINAL_KEYS}
	turn.update(kwargs)
	set_turn(conversation, turn)
	if turn.get("done"):
		frappe.flags[TURN_ANSWERED_FLAG] = True
	return turn


def clear_turn(conversation: str) -> None:
	frappe.cache.delete_value(_key(conversation))


def run_sync(coro):
	"""Run *coro* to completion from synchronous code, even when an event loop is already running."""
	try:
		asyncio.get_running_loop()
	except RuntimeError:
		return asyncio.run(coro)

	ctx = contextvars.copy_context()
	with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
		return pool.submit(ctx.run, asyncio.run, coro).result()
