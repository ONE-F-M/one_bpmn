# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Shared AG-UI event stream (WI-001670).

One generator turns any agent's turn — for any runner — into a valid AG-UI
event sequence: RunStarted → text content (and extension events) →
RunFinished, or RunError on failure. Generalized from the working Lumina
implementation (onefm_mcp lumina.py's ``ag_ui_event_generator`` /
``_bpmn_event_generator``) rather than written from scratch; like those, the
blocking turn runs between yields, so RunStarted flushes to the client before
the model is called.

Two reply shapes come back from ``invoke_agent(stream=True)``:

* a **buffered dict** (bpmn_map / direct_api / adk runners) — emitted as one
  TextMessage triple, then any extension events a registered translator
  derives from the payload;
* an **event generator** (the langgraph runner, i.e. today's BA agent) —
  relayed item by item with the same passthrough rules Lumina applies: the
  parent stream owns the run lifecycle, the child stream owns its messages.

Extension translation (payload dict → ``onefm.*`` CustomEvents) is a plug
point: WI-001670 ships the mechanism plus the one cross-agent mapping
(``onefm.choice``); the full contract mapping registers itself in WI-001671.

Transport rules (deliberate, from the WI-001671 contract decisions): SSE
keep-alives/heartbeats are comments, never events; errors surface only as
RunError; nothing is ever emitted as a bare named SSE line.
"""

import json
import uuid

import frappe
from ag_ui.core import (
	CustomEvent,
	RunErrorEvent,
	RunFinishedEvent,
	RunStartedEvent,
	TextMessageContentEvent,
	TextMessageEndEvent,
	TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder

# ── Extension translators (payload dict → list of CustomEvent) ──────────────
# Registered callables receive the runner's reply dict and return an iterable
# of ag_ui.core events (typically CustomEvent). The contract story
# (WI-001671) registers the full onefm.* mapping here.

_EXTENSION_TRANSLATORS = []


def register_extension_translator(fn):
	"""Register a callable(result_dict) -> iterable of events. Idempotent."""
	if fn not in _EXTENSION_TRANSLATORS:
		_EXTENSION_TRANSLATORS.append(fn)
	return fn


@register_extension_translator
def _choice_translator(result: dict):
	"""The one cross-agent mapping owned by WI-001670: an intent that asks
	the user to pick becomes ``onefm.choice`` — today's Logix DISAMBIGUATE
	and ProsAlly CONFIRM / CONFIRM_REMOVAL payloads."""
	intent = (result.get("intent") or "").upper()
	options = result.get("options") or []
	if intent in ("DISAMBIGUATE", "CONFIRM", "CONFIRM_REMOVAL") and options:
		yield CustomEvent(
			name="onefm.choice",
			value={
				"prompt": result.get("response") or "",
				"options": options,
				"action_intent": result.get("action_intent") or intent,
			},
		)


def _extension_events(result: dict):
	for fn in list(_EXTENSION_TRANSLATORS):
		try:
			yield from fn(result) or []
		except Exception:
			# A broken translator must never kill the transcript.
			frappe.log_error(title="agui extension translator error", message=frappe.get_traceback())


# ── The stream ───────────────────────────────────────────────────────────────


def agent_event_stream(agent_id: str, message: str, conversation: str, context: dict | None = None):
	"""Yield one agent turn as encoded AG-UI SSE lines.

	``conversation`` is required: the endpoint resolves/creates it *before*
	the stream opens so RunStarted can carry it as ``thread_id`` — the
	client learns its conversation id from the lifecycle event, not from a
	side channel.
	"""
	encoder = EventEncoder()
	run_id = str(uuid.uuid4())
	message_id = str(uuid.uuid4())

	yield encoder.encode(RunStartedEvent(run_id=run_id, thread_id=conversation))
	try:
		from one_bpmn.api.agent_invocation import invoke_agent

		result = invoke_agent(
			agent_id, message, conversation=conversation, context=context or {}, stream=True
		)

		if result.get("streaming"):
			yield from _relay_child_stream(result["stream"], encoder, message_id)
		else:
			text = result.get("response") or ""
			yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
			yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=text))
			yield encoder.encode(TextMessageEndEvent(message_id=message_id))
			for event in _extension_events(result):
				yield encoder.encode(event)
	except Exception as e:
		frappe.log_error(title="agui stream error", message=frappe.get_traceback())
		yield encoder.encode(RunErrorEvent(message=str(e)))
	finally:
		yield encoder.encode(RunFinishedEvent(run_id=run_id, thread_id=conversation))
		yield "\n"


def _relay_child_stream(child, encoder, message_id):
	"""Relay a streaming runner's events into the parent stream.

	Mirrors Lumina's passthrough rules (lumina.py ag_ui_event_generator):
	the parent owns RUN_STARTED / RUN_FINISHED, so the child's copies are
	dropped; a child RUN_ERROR raises so the parent emits exactly one
	terminal error; already-encoded strings pass through untouched; text
	deltas are re-encoded under the child's message id when it has one.
	"""
	for event in child:
		if isinstance(event, (bytes, str)):
			# Already an encoded SSE line (str) — trust and pass through.
			yield event.decode() if isinstance(event, bytes) else event
			continue
		if not isinstance(event, dict):
			yield encoder.encode(
				TextMessageContentEvent(message_id=message_id, delta=str(event))
			)
			continue

		event_type = (event.get("type") or "").upper()
		if event_type in ("RUN_STARTED", "RUN_FINISHED"):
			continue
		if event_type == "RUN_ERROR":
			raise Exception(event.get("message", "Unknown agent error"))
		if event_type == "TEXT_MESSAGE_CONTENT":
			delta = event.get("delta", "")
			if isinstance(delta, list):
				delta = "".join(
					d.get("text", str(d)) if isinstance(d, dict) else str(d) for d in delta
				)
			yield encoder.encode(
				TextMessageContentEvent(
					message_id=event.get("message_id", message_id), delta=delta
				)
			)
			continue
		# Everything else — TEXT_MESSAGE_START/END, TOOL_CALL_*, STATE_*,
		# CUSTOM — passes through as a data line, exactly as Lumina does.
		yield f"data: {json.dumps(event, default=str)}\n\n"
