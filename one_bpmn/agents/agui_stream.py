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

import contextvars
import json
import time
import threading
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
	ToolCallEndEvent,
	ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from frappe import _

from one_bpmn.security.rate_limit import RateLimited
from one_bpmn.security.refusal import AgentRefusal

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


def _iter_text_deltas(text: str, chunk_chars: int = 60):
	"""Split a reply into delta-sized chunks for progressive
	TextMessageContent emission.

	A short reply \u2014 the common case, and every reply in the earlier
	tests \u2014 still comes out as exactly one chunk, so callers that assumed
	one delta per turn keep working unchanged. Anything longer is cut only
	at whitespace, never mid-word, and ``"".join(chunks) == text`` always:
	the client concatenates deltas to build the message, so a chunk
	boundary must never lose or duplicate a character.
	"""
	if not text:
		return
	length = len(text)
	if length <= chunk_chars:
		yield text
		return
	start = 0
	while start < length:
		end = min(start + chunk_chars, length)
		if end < length:
			next_space = text.find(" ", end)
			end = next_space + 1 if next_space != -1 else length
		yield text[start:end]
		start = end


def _tool_calls_from_result(result: dict) -> list:
	"""Tool calls that ran during a buffered turn.

	A buffered runner (bpmn_map / direct_api / adk) has already finished by
	the time its reply reaches this stream, so there is no live moment to
	hang a TOOL_CALL_START/END pair on \u2014 they are emitted here, together,
	from whatever record of the turn's tool calls the reply carries.
	Prefers an explicit ``tool_calls`` list on the reply; falls back to
	flattening the AI Agent Run's own per-turn ``trace`` (the
	TurnRecord/ToolCallRecord shape from agents/llm_provider/base.py) when
	a runner exposes that instead. Neither present is not an error \u2014 most
	turns call no tools at all.
	"""
	calls = result.get("tool_calls")
	if calls:
		return list(calls)
	flattened = []
	for turn in result.get("trace") or []:
		flattened.extend((turn or {}).get("tool_calls") or [])
	return flattened


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


_HEARTBEAT_INTERVAL_SECONDS = 10
# The longest the stream waits for a turn to produce anything at all. Matches
# the ceiling one AI task is given, so a slow turn is never cut off, while a
# turn whose worker died stops holding the connection open with keep-alives.
_STALL_CEILING_SECONDS = 300
_TIMED_OUT = object()


def _invoke_with_heartbeat(fn, interval: float = _HEARTBEAT_INTERVAL_SECONDS, timeout: float | None = None):
	"""Run a blocking callable off-thread, yielding an SSE keep-alive comment
	every ``interval`` seconds so an idle proxy cannot close a working turn.

	Consume with ``result = yield from _invoke_with_heartbeat(fn)``. A
	keep-alive is transport, so it is a bare SSE comment, never an encoded
	event.
	"""
	outcome: dict = {}
	# frappe.local is a ContextVar, and a thread starts with an empty context,
	# so the call runs inside a copy of this request's or it loses the session,
	# the site and frappe.flags.
	context = contextvars.copy_context()

	def _run():
		try:
			outcome["result"] = context.run(fn)
		except BaseException as exc:  # noqa: BLE001 - re-raised on caller's thread
			outcome["error"] = exc

	thread = threading.Thread(target=_run, daemon=True)
	thread.start()
	deadline = None if timeout is None else time.monotonic() + timeout
	while True:
		thread.join(timeout=interval)
		if not thread.is_alive():
			break
		if deadline is not None and time.monotonic() >= deadline:
			# The thread is left running: it holds a database cursor this
			# generator no longer owns, and killing it is not on offer. It ends
			# with the request.
			return _TIMED_OUT
		yield ": keep-alive\n\n"

	if "error" in outcome:
		raise outcome["error"]
	return outcome.get("result")


def agent_event_stream(
	agent_id: str,
	message: str,
	conversation: str,
	context: dict | None = None,
	client_message_id: str | None = None,
):
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

		result = yield from _invoke_with_heartbeat(
			lambda: invoke_agent(
				agent_id,
				message,
				conversation=conversation,
				context=context or {},
				stream=True,
				client_message_id=client_message_id,
			)
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
			# A handover is taken out of the relay and falls through to the
			# buffered path, so cards and artifacts keep working.
			handover = {}
			yield from _relay_child_stream(
				_take_handover(result["stream"], handover), encoder, message_id, state=handover
			)
			if "result" not in handover:
				_commit_turn()
				result = None
			else:
				result = handover["result"]
				if handover.get("text_streamed") and isinstance(result, dict):
					result["text_streamed"] = True
					result["streamed_text"] = handover.get("streamed_text") or ""

		if result is not None and not result.get("streaming"):
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
			# the stream itself starts (and the RunStarted event
			# above already went out) before invoke_agent returns, so before
			# this point there is no Bot Chat Message row to name the
			# message after — `message_id` stays the id generated at the top
			# of this function for the WHOLE lifecycle of the streamed
			# message (start, every delta, end). Once the runner's reply is
			# in hand the persisted Chat Message name IS known,
			# so it is delivered separately, at the end, as the durable id a
			# rating or report should point at — never by silently swapping
			# the id already used for events the client already rendered.
			persisted_name = result.get("message_name")
			# AG-UI rejects an empty delta (min_length=1), so a runner that
			# produced no text used to abort the whole stream with a validation
			# error — the user saw a failed request rather than an answer. An
			# empty reply is a thing that happens (a failed AI task leaves the
			# output variable blank), so it is reported, not raised.
			extensions = list(_extension_events(result))
			tool_calls = _tool_calls_from_result(result)
			if not text and not extensions and not tool_calls:
				text = _(
					"The agent finished without producing a reply. Please try again."
				)
			if result.get("text_streamed"):
				# The reader already has the text, word by word, from the relay.
				# Sending it again would show the reply twice.
				yield encoder.encode(TextMessageEndEvent(message_id=message_id))
			if not result.get("text_streamed") or not _same_text(result.get("streamed_text"), text):
				# A map may compose its reply after the model spoke (a finalize
				# tool, a reply shaper), so what streamed is not always the answer.
				yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
				# One TextMessageContent per chunk: the runner finished before
				# this point, but the reader still sees the text arrive in
				# pieces instead of all at once.
				for delta in _iter_text_deltas(text):
					yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=delta))
				yield encoder.encode(TextMessageEndEvent(message_id=message_id))
			# TOOL_CALL_START/END bracket each tool the turn ran,
			# named for the tool shape that ran it — the same names already
			# recorded on the turn's ToolCallRecord/tool_calls entries, so a
			# client showing "using <tool>…" names the same thing the trace
			# does. The buffered runner already finished every call before
			# this reply reached the stream, so start/end are emitted back to
			# back rather than bracketing a live wait.
			for call in tool_calls:
				tool_call_id = str((call or {}).get("id") or uuid.uuid4())
				tool_name = (call or {}).get("name") or ""
				yield encoder.encode(
					ToolCallStartEvent(tool_call_id=tool_call_id, tool_call_name=tool_name)
				)
				yield encoder.encode(ToolCallEndEvent(tool_call_id=tool_call_id))
			for event in extensions:
				yield encoder.encode(event)
			# The generated stream id is what every event above was keyed to;
			# once the Chat Message is actually saved (unchanged: still
			# wherever the runner/hook already does it) its real name is
			# handed over here so the client can attach a rating/report to
			# the durable record instead of the throwaway stream id.
			if persisted_name and persisted_name != message_id:
				yield encoder.encode(
					CustomEvent(
						name="onefm.message_persisted",
						value={"stream_id": message_id, "message_name": persisted_name},
					)
				)
			_commit_turn()
	except AgentRefusal as refusal:
		# RateLimited, an injection Block, a model with broken credentials
		# (WI-002191): every refusal derives from AgentRefusal for exactly this
		# handler, so a new control is shown verbatim without teaching the
		# stream its name.
		# A throttle or a conversation freeze is a DECISION, not a fault. Every
		# older surface already knew that; this shared stream did not, so a
		# refusal arrived as RUN_ERROR and the panel showed "Something went
		# wrong" over a message that explains itself perfectly well.
		#
		# Delivered as a system notice, not an assistant message: a throttle is
		# the platform talking. Not logged as an error either, since a control
		# working as designed is not an incident.
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
		text = str(refusal) or _("This agent declined to answer that message.")
		yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="system"))
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


# A streaming runner ends by handing its buffered reply over on the same
# stream, so the shaping is not duplicated.
HANDOVER_EVENT = "ONEFM_TURN_RESULT"

_CHILD_EXHAUSTED = object()


def _same_text(streamed, final) -> bool:
	"""Did the reader already see this reply, word for word?"""
	a = " ".join((streamed or "").split())
	b = " ".join((final or "").split())
	if not a or not b:
		return False
	return a == b or a in b or b in a


def _take_handover(child, handover: dict):
	"""Relay a child's events, keeping the handover event out of the stream."""
	for event in child:
		if isinstance(event, dict) and event.get("type") == HANDOVER_EVENT:
			handover["result"] = event.get("result") or {}
			return
		yield event


def _relay_child_stream(
	child, encoder, message_id, interval=_HEARTBEAT_INTERVAL_SECONDS,
	stall_ceiling=_STALL_CEILING_SECONDS, state=None,
):
	"""Relay a streaming runner's events into the parent stream.

	Mirrors Lumina's passthrough rules (lumina.py ag_ui_event_generator):
	the parent owns RUN_STARTED / RUN_FINISHED, so the child's copies are
	dropped; a child RUN_ERROR raises so the parent emits exactly one
	terminal error; already-encoded strings pass through untouched; text
	deltas are re-encoded under the child's message id when it has one.
	"""
	# A child that is waiting on a worker yields nothing for as long as the
	# work takes, so the wait for its next event is what has to carry the
	# keep-alive, not the call that produced the child.
	steps = iter(child)
	while True:
		event = yield from _invoke_with_heartbeat(
			lambda: next(steps, _CHILD_EXHAUSTED), interval, timeout=stall_ceiling
		)
		if event is _CHILD_EXHAUSTED:
			return
		if event is _TIMED_OUT:
			# A keep-alive says the connection is open, not that the work is
			# alive. A worker killed mid-turn leaves nothing to end the wait, so
			# the stream ends it and says so.
			yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="system"))
			yield encoder.encode(
				TextMessageContentEvent(
					message_id=message_id,
					delta=_(
						"This turn stopped responding. Nothing you typed was lost — "
						"send it again when you are ready."
					),
				)
			)
			yield encoder.encode(TextMessageEndEvent(message_id=message_id))
			return
		if isinstance(event, (bytes, str)):
			# Already an encoded SSE line (str) — trust and pass through.
			yield event.decode() if isinstance(event, bytes) else event
			continue
		if not isinstance(event, dict):
			text = str(event)
			if text:
				yield encoder.encode(
					TextMessageContentEvent(message_id=message_id, delta=text)
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
				# "type", and the BA Agent's bridge yields new_mode the same way
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
		if event_type == "TOOL_CALL_START" and state is not None and state.get("text_streamed"):
			# Text before a tool call is the agent talking to itself. Close it so
			# the words after the tool open a fresh reply, and forget it so the
			# buffered path compares only the last stretch with the final answer.
			yield encoder.encode(TextMessageEndEvent(message_id=message_id))
			state["text_streamed"] = False
			state["streamed_text"] = ""
		if event_type == "TEXT_MESSAGE_CONTENT":
			delta = event.get("delta", "")
			if isinstance(delta, list):
				delta = "".join(
					d.get("text", str(d)) if isinstance(d, dict) else str(d) for d in delta
				)
			# Nothing to relay, and AG-UI will not accept an empty delta — a
			# child's keep-alive chunk must not end the parent's stream.
			if not delta:
				continue
			# Text arriving while the turn runs opens the reply the first time,
			# and tells the buffered path afterwards that the reader has it.
			if state is not None and not state.get("text_streamed"):
				state["text_streamed"] = True
				yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
			if state is not None:
				state["streamed_text"] = (state.get("streamed_text") or "") + delta
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
