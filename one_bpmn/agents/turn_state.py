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
import contextvars

import frappe


def _key(conversation: str) -> str:
    return f"ait_turn:{conversation}"


def get_turn(conversation: str) -> dict:
    """Return the current turn scratch dict (empty dict if none).

    Reads PAST frappe's in-process memo rather than through it. ``get_value``
    returns ``frappe.local.cache[key]`` whenever the key is present and never
    consults Redis, and a stage tool's write does not reliably survive into the
    caller's local cache — so ``Save Response`` could read a copy of the turn
    from before ``finalize`` had answered it. Redis held the answer the whole
    time; only the memo was stale.

    The consequence was total rather than subtle. With no ``output`` visible,
    ``Save Response`` falls back to the agent's own final text, and the protocol
    makes that the literal word ``DONE`` — so a full analysis was published as
    one word, the transcript recorded ``DONE`` as what the agent had said, and
    the next turn was fed that as its history. Every agent sharing this store is
    exposed to it, which is why the fix belongs here and not in one agent's
    Save Response script.
    """
    key = _key(conversation)
    # Drop the memo for this key first: Redis is the authority for a value another
    # execution context may have written since this one last looked.
    frappe.local.cache.pop(frappe.cache.make_key(key), None)
    return frappe.cache.get_value(key) or {}


def set_turn(conversation: str, data: dict) -> None:
    frappe.cache.set_value(_key(conversation), data)


# The keys that END a turn: ``output`` is the reply ``Save Response`` persists,
# ``done`` marks it final. They are write-once — see update_turn below.
_TERMINAL_KEYS = ("output", "done")

# Set on frappe.flags the moment a stage tool answers the turn, so the agent
# loop can stop instead of paying for one more model call that has nothing left
# to say. It lives here beside the write-once guard because both express the
# same fact — this turn is over — and the store is the only layer that sees it
# happen. Read and cleared by agents/executor/step_loop.py, exactly as
# shape_tools.PAUSE_HELD_FLAG is.
TURN_ANSWERED_FLAG = "bpmn_turn_answered"


def update_turn(conversation: str, **kwargs) -> dict:
    """Merge ``kwargs`` into the turn scratch and persist it. Returns the result.

    The terminal keys are WRITE-ONCE: the first stage tool to answer the turn
    owns the reply, and a later tool cannot overwrite it (WI-002001).

    Without this the store was last-writer-wins, and the orchestrating LLM only
    has to call one extra stage tool to destroy a finished turn. Observed live in
    ProsAlly: on a confirmed MODIFY_EXISTING the tool sequence should be
    ``classify_intent → modify_process → finalize``, but roughly two turns in five
    came back ``classify_intent → modify_process → confirm → finalize``. The work
    was done — ``modify_process`` had already written a CONFIRM_REMOVAL output
    carrying the rebuilt diagram — and the stray ``confirm`` call replaced it with
    a fresh "Shall I go ahead?". ``Save Response`` then persisted the clobbered
    reply, so the designer re-confirmed, and the turn looped forever while the
    diagram it asked for was silently thrown away every pass.

    A stage tool that finishes its own work is not the right place to police
    this: it cannot know another tool ran after it. The invariant belongs to the
    store, which is also why one guard here covers every agent that shares it
    (ProsAlly, Logix, Docu, LuCrusher). Non-terminal keys in the same call still
    apply, so nothing else is lost. ``Build Context`` seeds each turn with a
    fresh ``set_turn``, which clears ``done`` — the guard is per-turn, never
    across turns.
    """
    turn = get_turn(conversation)
    if turn.get("done") and any(k in kwargs for k in _TERMINAL_KEYS):
        _existing = turn.get("output")
        _kept = _existing.get("intent") if isinstance(_existing, dict) else None
        _attempted = kwargs.get("output")
        _dropped = _attempted.get("intent") if isinstance(_attempted, dict) else None
        frappe.logger("one_bpmn").warning(
            f"turn_state: refused a second terminal write on conversation {conversation} "
            f"— kept intent={_kept!r}, dropped intent={_dropped!r}. A stage tool ran "
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
    """
    Run *coro* to completion from synchronous code, even when an event loop is
    already running.

    Stage tools are invoked synchronously from inside the LLM adapter's async
    tool-calling loop (anthropic_adapter.complete → ``tool.fn(...)`` while the
    loop is running), so a plain ``asyncio.run`` would raise "cannot be called
    from a running event loop". When a loop is running we run the coroutine on a
    dedicated thread with its own loop; otherwise ``asyncio.run`` is fine.

    The thread must inherit the caller's context. ``frappe.local`` is a
    ContextVar-backed werkzeug Local (werkzeug ≥ 2.0), so a bare thread starts
    with no site, no ``frappe.db`` and no session: every frappe call inside
    *coro* then dies with "RuntimeError: object is not bound". That is invisible
    from the outside, because a sub-agent's read tools catch their own
    exceptions and hand the LLM an empty result — so the model silently goes
    blind to the live schema instead of failing loudly.

    Copying the context across fixes it and keeps one transaction: the thread
    shares the parent's database connection, which is safe because the parent
    blocks on ``.result()`` for the whole call, so the two never touch it
    concurrently. Writes the coroutine makes land in the caller's transaction,
    exactly as they do on the non-threaded path.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()
