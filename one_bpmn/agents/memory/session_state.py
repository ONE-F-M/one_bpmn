"""
A conversation's scratchpad: structured values an agent accumulates across
turns, outside both the message log and long-term memory.

Agents gather things as a conversation goes: a doctype being designed, fields
agreed so far, a decision awaiting confirmation. Today that has nowhere honest
to live. Long-term memory is for durable facts worth recalling on unrelated
runs, and this is neither durable nor general. The message log holds the
conversation, not a structured view of it, and re-deriving parameters by asking
a model to re-read the transcript every turn is both expensive and unreliable.

**Why not BPMN process variables**, which already persist across turns in
``task.data``? Measured before building this, on the three grounds the story
named:

- *Size* — variables live in ``BPMN Process Instance.workflow_state``, a
  longtext carrying the whole SpiffWorkflow serialization. Across 5,189
  instances: average 40KB, largest 729KB. Every write rewrites all of it.
- *Queryability* — that is JSON inside longtext with no index. "Which
  conversations have this parameter set" is a scan of roughly 200MB.
- *Lifecycle* — the decisive one. A resumed conversation gets a BRAND NEW
  instance: the map's close branch completes the old one, and the resume
  re-arms through the conditional start (see ``_run_bpmn_map``). 815 chat
  conversations already have a non-Active instance. State scoped to the
  instance therefore cannot survive the conversation it belongs to.

So state is scoped to the CONVERSATION, which is the thing that actually
persists.

Concurrency is handled by an explicit version rather than by a lock. Two turns
can overlap — a retry beside the run it retries, two tool calls finishing
together — and the failure to prevent is the silent one: both read version 4,
both write, and the second quietly erases the first. A caller passes back the
version it read; a write against a stale version is REFUSED, loudly, so the
caller can re-read and merge. Locking instead would block a turn for the length
of an LLM call.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

STATE_DOCTYPE = "Chat Session State"
ENTRY_DOCTYPE = "Chat Session State Entry"


class StaleSessionState(frappe.ValidationError):
	"""Raised when a write is made against a version that has moved on.

	Its own class so a caller can retry the read-modify-write, which is the only
	sensible response — and can tell it apart from the state being malformed,
	which retrying would not fix.
	"""


def _dumps(value) -> str:
	try:
		return json.dumps(value)
	except (TypeError, ValueError):
		# A value that will not serialise is stored as its string form rather
		# than rejected: losing the type of one key is better than failing the
		# agent turn that was trying to record it.
		return json.dumps(str(value))


def _loads(raw):
	if raw is None or raw == "":
		return None
	try:
		return json.loads(raw)
	except (TypeError, ValueError):
		# Written before this module, or edited by hand in Desk. Hand it back as
		# the text it is rather than pretending the row does not exist.
		return raw


# ── reading ─────────────────────────────────────────────────────────────────
def read_state(conversation: str) -> tuple[dict, int]:
	"""``(values, version)`` for a conversation. ``({}, 0)`` when it has none.

	Version 0 for an absent state is not a placeholder — it is the value a
	first writer must pass to claim it, so creating and updating are the same
	call with the same rule.
	"""
	if not conversation or not frappe.db.exists(STATE_DOCTYPE, conversation):
		return {}, 0
	doc = frappe.get_doc(STATE_DOCTYPE, conversation)
	return {row.key: _loads(row.value) for row in (doc.entries or [])}, int(doc.version or 0)


def get_state(conversation: str) -> dict:
	"""Just the values, for callers that are not writing."""
	return read_state(conversation)[0]


def get_value(conversation: str, key: str, default=None):
	return get_state(conversation).get(key, default)


def conversations_with(key: str, value=None) -> list[str]:
	"""Conversations whose scratchpad has ``key`` (optionally equal to ``value``).

	The reason entries are rows rather than one blob. This is an indexed filter;
	against a JSON blob it would be a full scan of every state on the site.
	"""
	filters = {"parenttype": STATE_DOCTYPE, "key": key}
	if value is not None:
		filters["value"] = _dumps(value)
	return frappe.get_all(ENTRY_DOCTYPE, filters=filters, pluck="parent", distinct=True)


# ── writing ─────────────────────────────────────────────────────────────────
def set_state(conversation: str, values: dict, expected_version: int | None = None,
              merge: bool = True) -> int:
	"""Write ``values`` and return the new version.

	``expected_version`` is the version the caller read. A mismatch raises
	:class:`StaleSessionState` rather than overwriting — the whole point, since
	the failure being prevented is the silent one. ``None`` skips the check, for
	a caller that genuinely owns the state and is not merging.

	``merge`` keeps keys the caller did not mention, which is almost always what
	an agent wants: a turn that learned one thing should not erase the four
	things earlier turns learned. Setting a key to ``None`` removes it.
	"""
	if not conversation:
		frappe.throw(_("Session state requires a conversation."))
	if not isinstance(values, dict):
		frappe.throw(_("Session state values must be a dict."))

	doc = _get_or_create(conversation)
	current = int(doc.version or 0)
	if expected_version is not None and int(expected_version) != current:
		raise StaleSessionState(
			_("Session state for {0} has moved on (expected version {1}, found {2}). "
			  "Re-read it and apply the change again.").format(conversation, expected_version, current)
		)

	merged = {row.key: row.value for row in (doc.entries or [])} if merge else {}
	for key, value in values.items():
		if value is None:
			merged.pop(key, None)
		else:
			merged[str(key)] = _dumps(value)

	doc.set("entries", [{"key": k, "value": v} for k, v in sorted(merged.items())])
	doc.version = current + 1
	try:
		doc.save(ignore_permissions=True)
	except frappe.TimestampMismatchError as e:
		# Frappe's own check caught what the version check could not: a caller
		# that passed no expected_version, or one whose read and write straddled
		# somebody else's save. Same situation, so raise the same error — a
		# caller should not have to know which layer noticed, and both mean
		# "refused, re-read and try again".
		raise StaleSessionState(
			_("Session state for {0} changed while this turn was writing it. "
			  "Re-read it and apply the change again.").format(conversation)
		) from e
	return doc.version


def update_state(conversation: str, expected_version: int | None = None, **values) -> int:
	"""Keyword form of :func:`set_state`, for readability at the call site."""
	return set_state(conversation, values, expected_version=expected_version)


def clear_state(conversation: str) -> None:
	if conversation and frappe.db.exists(STATE_DOCTYPE, conversation):
		frappe.delete_doc(STATE_DOCTYPE, conversation, force=True, ignore_permissions=True)


# ── the convention agents use ───────────────────────────────────────────────
# Everything below is what a map's Server Scripts call. It lives here rather
# than in each script so five agents share one behaviour instead of five
# near-copies that drift — which is what happened to the history window, where
# every Build Context grew its own query with its own limit.

RECORD_RETRIES = 3


def record(conversation: str, values: dict, retries: int = RECORD_RETRIES) -> int:
	"""Write decisions, re-reading and re-applying if another turn got there first.

	The retry belongs HERE, not in each agent's script. A stale write is a normal
	outcome when turns overlap, and the correct response is always the same: read
	the current version, apply your change to it, write again. Leaving that to
	five Server Scripts would mean five chances to skip it — and skipping it
	surfaces a lock error to somebody who asked a chat question.

	Returns the new version, or 0 if it could not be written. Never raises: a
	scratchpad that cannot be updated must not fail the turn that was trying to
	update it — the agent simply carries on without the benefit.
	"""
	if not conversation or not values:
		return 0
	for attempt in range(max(retries, 1)):
		try:
			_, version = read_state(conversation)
			return set_state(conversation, values, expected_version=version)
		except StaleSessionState:
			if attempt == retries - 1:
				frappe.logger("one_bpmn").warning(
					f"Session state for {conversation} stayed contended over "
					f"{retries} attempts; this turn's values were not recorded."
				)
			continue
		except Exception:
			frappe.log_error(
				title="Session state: could not record a turn's values",
				message=f"conversation={conversation}\n{frappe.get_traceback()}",
			)
			return 0
	return 0


def for_prompt(conversation: str, header: str = "Established so far in this conversation:") -> str:
	"""The scratchpad as a block to put in front of the model, or "" when empty.

	Rendered as JSON rather than prose because it IS structured — and because the
	point is to stop the model re-deriving these values from the transcript, so
	handing them back as prose it has to parse again would only move the problem.

	Returns "" for an empty state so a caller can concatenate unconditionally
	without producing an empty heading.
	"""
	state = get_state(conversation)
	if not state:
		return ""
	return header + "\n" + json.dumps(state, indent=2, default=str)


def _get_or_create(conversation: str):
	"""The state row for a conversation, created on first write.

	The doctype is named AFTER its conversation, so two turns creating it at the
	same moment collide on the primary key rather than producing two states —
	the same guarantee the conversation store needed, for the same reason, and
	learned the same painful way.
	"""
	if frappe.db.exists(STATE_DOCTYPE, conversation):
		return frappe.get_doc(STATE_DOCTYPE, conversation)

	doc = frappe.get_doc({"doctype": STATE_DOCTYPE, "conversation": conversation, "version": 0})
	try:
		frappe.db.savepoint("session_state_create")
		doc.insert(ignore_permissions=True)
		# Published immediately so a concurrent creator collides with a row it
		# can see, rather than blocking on an invisible one.
		frappe.db.commit()
	except Exception:
		frappe.db.rollback(save_point="session_state_create")
		# Under REPEATABLE READ this transaction's snapshot predates the winner,
		# so a plain re-read would still not find it. Commit for a fresh one.
		frappe.db.commit()
		if frappe.db.exists(STATE_DOCTYPE, conversation):
			return frappe.get_doc(STATE_DOCTYPE, conversation)
		raise
	return doc
