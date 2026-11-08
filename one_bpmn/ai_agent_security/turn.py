# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
One id shared by everything a single agent turn produces (WI-001967).

A turn writes records at moments that cannot see each other. The input screen
runs before the BPMN map dispatches, so no AI Agent Run exists yet; the run is
created later, inside the dispatcher. A security event therefore cannot name the
run it preceded — and it cannot be back-filled either, because the event is
immutable by design.

The standard answer is not to link the records but to stamp them. A correlation
id minted at the start of the turn is attached to the security event and reused
as the run's own ``correlation_id``, so the join is exact without either record
having to know about the other, and without anything being edited after the
fact.

Held in a ContextVar so concurrent turns keep their own id instead of racing.
Nothing here ever raises: a turn with no id simply produces records that cannot
be joined, which is where we were before.
"""

from __future__ import annotations

from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("one_bpmn_turn_correlation_id", default=None)


def begin_turn(correlation_id: str | None = None) -> str:
	"""Start a turn and return its correlation id, generating one if needed.

	Returns the id so the caller can reset it later; calling this twice in one
	turn deliberately mints a new id, because that is a new turn.
	"""
	if not correlation_id:
		try:
			import frappe

			correlation_id = frappe.generate_hash(length=16)
		except Exception:
			import uuid

			correlation_id = uuid.uuid4().hex[:16]
	_correlation_id.set(correlation_id)
	return correlation_id


def current_correlation_id() -> str | None:
	"""The current turn's id, or None outside a turn."""
	try:
		return _correlation_id.get()
	except Exception:
		return None


def end_turn() -> None:
	"""Clear the id so a pooled worker does not leak it into the next turn."""
	try:
		_correlation_id.set(None)
	except Exception:
		pass
