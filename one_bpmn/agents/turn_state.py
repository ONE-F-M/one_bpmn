# Copyright (c) 2026, one-fm and contributors
"""
Per-turn scratch store shared by an AI Agent Task's stage tools.

The Camunda "tools are the shapes" model executes each tool shape in a *fresh*
synthetic task (see agents/shape_tools.py): a tool cannot receive LLM arguments
and cannot see the workflow's ``task.data``. Pipeline-stage tools therefore need
a side channel to accumulate the turn's intermediate results (intent → draft →
review → final output). That channel is this store, keyed by conversation.

It is deliberately Redis-backed (frappe.cache): a chat turn runs as one
synchronous engine pass, so every stage tool and the final "Save Response" step
share the same process and the same cache. ``Build Context`` seeds the turn
inputs and clears any stale state; ``finalize`` writes the structured output
that ``Save Response`` reads back.
"""

from __future__ import annotations

import asyncio
import concurrent.futures

import frappe


def _key(conversation: str) -> str:
    return f"ait_turn:{conversation}"


def get_turn(conversation: str) -> dict:
    """Return the current turn scratch dict (empty dict if none)."""
    return frappe.cache.get_value(_key(conversation)) or {}


def set_turn(conversation: str, data: dict) -> None:
    frappe.cache.set_value(_key(conversation), data)


def update_turn(conversation: str, **kwargs) -> dict:
    """Merge ``kwargs`` into the turn scratch and persist it. Returns the result."""
    turn = get_turn(conversation)
    turn.update(kwargs)
    set_turn(conversation, turn)
    return turn


def clear_turn(conversation: str) -> None:
    frappe.cache.delete_value(_key(conversation))


def run_sync(coro):
    """
    Run *coro* to completion from synchronous code, even when an event loop is
    already running.

    Stage tools are invoked synchronously from inside the LLM adapter's async
    tool-calling loop (anthropic_adapter.complete → ``tool.fn(...)`` while the
    loop is running), so a plain ``asyncio.run`` would raise "cannot be called
    from a running event loop". When a loop is running we run the coroutine on a
    dedicated thread with its own loop; otherwise ``asyncio.run`` is fine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
