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
from frappe import _

from one_bpmn.security.rate_limit import RateLimited

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
	# A removal gate that carries the diagram is NOT loose buttons: the
	# confirm belongs inside the DiagramPreviewCard (WI-001671), so the
	# bpmn_preview translator owns that payload.
	if intent == "CONFIRM_REMOVAL" and result.get("pending_xml"):
		return
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


def _agent_artifact_type(agent_id: str) -> str:
	"""The agent's configured Artifact Type (WI-001996), for the generic
	artifact translator. Empty string when unset/unreadable — the translator
	then stands down, same as artifact_type 'None'."""
	try:
		return (
			frappe.db.get_value(
				"AI Agent Configuration", {"agent_id": agent_id, "enabled": 1}, "artifact_type"
			)
			or ""
		)
	except Exception:
		return ""



# ── Per-agent hooks (WI-001674) ──────────────────────────────────────────────
# Context builders enrich the raw grounding a surface sends into the turn
# context an agent's map expects (e.g. the assistant's dialog_context).
# Reply shapers post-process a buffered reply BEFORE its text is emitted —
# the seam that keeps structured JSON out of chat bubbles for agents whose
# maps still answer in the legacy text contract.

_CONTEXT_BUILDERS = {}
_REPLY_SHAPERS = {}


def register_context_builder(agent_id, fn):
	"""fn(context: dict) -> dict, applied before invoke_agent."""
	_CONTEXT_BUILDERS[agent_id] = fn
	return fn


def register_reply_shaper(agent_id, fn):
	"""fn(result: dict) -> dict, applied to buffered replies before text emission."""
	_REPLY_SHAPERS[agent_id] = fn
	return fn


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

		builder = _CONTEXT_BUILDERS.get(agent_id)
		if builder:
			context = builder(context or {})

		result = invoke_agent(
			agent_id, message, conversation=conversation, context=context or {}, stream=True
		)

		# SSE has no request-success commit: the whitelisted handler returned
		# the moment the Response was constructed, so everything the turn
		# wrote — bot message, workflow state, run rollups — would silently
		# roll back when the connection closes. Commit inside the stream,
		# exactly as the production Lumina generator does. (Guarded for the
		# test runner's transaction isolation.)
		def _commit_turn():
			if not frappe.flags.in_test:
				frappe.db.commit()

		if result.get("streaming"):
			yield from _relay_child_stream(result["stream"], encoder, message_id)
			_commit_turn()
		else:
			shaper = _REPLY_SHAPERS.get(agent_id)
			if shaper:
				try:
					result = shaper(result) or result
				except Exception:
					frappe.log_error(title="agui reply shaper error", message=frappe.get_traceback())
			# WI-001996 wiring: a generic `artifact` reply renders through the
			# typed event named by the agent's configured Artifact Type. The
			# type is resolved here — the only layer that knows agent_id — so
			# the translator itself stays agent-blind. A reply's own
			# artifact_type key wins, letting one map serve several kinds.
			if result.get("artifact") is not None and not result.get("artifact_type"):
				result["artifact_type"] = _agent_artifact_type(agent_id)
			text = result.get("response") or ""
			# The AG-UI message_id IS the persisted Chat Message name whenever the
			# runner saved one (WI-001641). `message_id` exists in the protocol to
			# identify a message; minting a uuid for it and throwing it away left
			# the client unable to name the reply it had just been shown, so a
			# rating or a report had nothing durable to point at. Runners that
			# persist nothing keep the generated id, which is still unique per
			# turn and still correct for grouping the text events.
			message_id = result.get("message_name") or message_id
			yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
			yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=text))
			yield encoder.encode(TextMessageEndEvent(message_id=message_id))
			for event in _extension_events(result):
				yield encoder.encode(event)
			_commit_turn()
	except RateLimited as refusal:
		# A throttle or a conversation freeze is a DECISION, not a fault. Every
		# older surface already knew that; this shared stream did not, so a
		# refusal arrived as RUN_ERROR and the panel showed "Something went
		# wrong" over a message that explains itself perfectly well.
		#
		# Delivered as an ordinary assistant message so it lands in the thread
		# where the user is reading, and NOT logged as an error: the control
		# working as designed is not an incident, and a traceback per refusal
		# fills the log with false alarms.
		# COMMIT, not rollback. Nothing of this turn has been written — enforce
		# raises before the runner is reached — so the only thing in the
		# transaction is the AI Security Event recording the blocked attempt, and
		# that is the one thing that must survive.
		#
		# Rolling back here (copied from the generic handler below, where it is
		# right) threw that record away. It cost the audit trail, and it silently
		# disabled the freeze on this surface: blocked_attempts counts those
		# events, so the count could never rise and containment could never
		# trigger no matter how hard someone hammered the door. Six refusals in a
		# row had logged exactly one attempt.
		if not frappe.flags.in_test:
			frappe.db.commit()
		text = str(refusal) or _("You are sending messages to this agent too quickly.")
		yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
		yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=text))
		yield encoder.encode(TextMessageEndEvent(message_id=message_id))
	except Exception as e:
		if not frappe.flags.in_test:
			frappe.db.rollback()
		frappe.log_error(
			title="agui stream error",
			message=f"agent={agent_id} conversation={conversation} user={frappe.session.user}\n\n"
			+ frappe.get_traceback(),
		)
		yield encoder.encode(RunErrorEvent(message=str(e)))
	finally:
		yield encoder.encode(RunFinishedEvent(run_id=run_id, thread_id=conversation))
		yield "\n"


# Keys that belong to the CUSTOM envelope itself; everything else a legacy
# producer puts on the event is payload (see _relay_child_stream).
_CUSTOM_ENVELOPE_KEYS = {"type", "name", "event", "value", "timestamp", "raw_event", "rawEvent"}


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
		if event_type == "CUSTOM":
			# WI-001680: legacy child event names adopt their contract names
			# at the relay boundary, so every CUSTOM event on the wire is
			# namespaced (MODE_TRANSITION had no consumer before this;
			# LUCRUSHER_RESULT keeps its payload, envelope renamed).
			renames = {
				"MODE_TRANSITION": "onefm.mode_transition",
				"LUCRUSHER_RESULT": "onefm.lucrusher_result",
				"HEARTBEAT": None,  # keep-alives are transport, never events
			}
			raw_name = event.get("name") or event.get("event") or ""
			if raw_name in renames:
				new_name = renames[raw_name]
				if new_name is None:
					continue
				# The legacy producers put their payload FLAT on the event —
				# lumina.py yields intent/matches/topology/… as siblings of
				# "type", and user_planning_agent yields new_mode the same way
				# — while an AG-UI CustomEvent carries it under `value`, which
				# is all the panel reads. Renaming alone therefore delivered
				# an EMPTY event to every consumer (WI-001678): fold the
				# producer's own keys into value, preferring an explicit
				# `value` when the producer already speaks the contract.
				value = dict(event.get("value") or {})
				for key, val in event.items():
					if key not in _CUSTOM_ENVELOPE_KEYS:
						value.setdefault(key, val)
				event = {k: v for k, v in event.items() if k in _CUSTOM_ENVELOPE_KEYS}
				event.update({"name": new_name, "value": value})
				event.pop("event", None)
			yield f"data: {json.dumps(event, default=str)}\n\n"
			continue
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


# ── Contract translators (WI-001671) ─────────────────────────────────────────
# Importing the contract package registers the full onefm.* payload mapping.
# Guarded so a broken contract module degrades to text-only streams instead of
# killing every chat endpoint at import time.
try:
	from one_bpmn.agents.agui_contract import translators as _contract_translators  # noqa: F401,E402
except Exception:
	frappe.log_error(title="agui contract translators failed to load", message=frappe.get_traceback())

# The assistant registers its context builder + reply shaper on import
# (WI-001674). Same degrade-to-text guarantee as the translators.
try:
	import one_bpmn.api.ai_assistant  # noqa: F401,E402
except Exception:
	frappe.log_error(title="agui assistant hooks failed to load", message=frappe.get_traceback())

# Logix and ProsAlly register their context builders + reply shapers on import
# (WI-001677 / WI-001675 follow-ups from live testing).
try:
	import one_bpmn.api.server_script_api  # noqa: F401,E402
except Exception:
	frappe.log_error(title="agui logix hooks failed to load", message=frappe.get_traceback())

# Docu registers its context builder (current-IR loading) + reply shaper on
# import (WI-001676 follow-up). Same degrade-to-text guarantee.
try:
	import one_bpmn.api.docu_api  # noqa: F401,E402
except Exception:
	frappe.log_error(title="agui docu hooks failed to load", message=frappe.get_traceback())
