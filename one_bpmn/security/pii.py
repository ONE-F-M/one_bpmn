# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
PII detection and reversible redaction for agent input (WI-001644).

Every agent invocation carries whatever the user typed straight to a third-party
model. A Civil ID pasted into a chat box is, today, sent verbatim to Anthropic
and then written into the conversation log. This module intercepts that at the
one point every invocation passes through and replaces detected values with
tokens BEFORE the text reaches a model or is stored.

REVERSIBLE, NOT DESTRUCTIVE
---------------------------
"Find the employee with Civil ID 289010112345" has to keep working, so a
detected value becomes a stable token — ``[CIVIL_ID_1]`` — and the mapping is
held for the duration of the turn. The model reasons about the token; when it
calls a tool, the token is swapped back for the real value at the tool boundary
(see ToolSpec.__post_init__). The model never sees the value; the lookup still
resolves.

The mapping lives in a ContextVar, not on the document: it exists for one turn
and is discarded, so a redacted transcript can never be re-identified later from
anything this module persists.

DETECTION IS DELIBERATELY CONSERVATIVE
--------------------------------------
Two rules, both aimed at false positives, because a screen that mangles ordinary
text gets switched off within a week:

  * Every numeric detector that HAS a checksum uses it. A Kuwait Civil ID and a
    payment card are both verified arithmetically, not just shape-matched.
  * Detectors whose shape genuinely collides with ordinary text (passport
    numbers are the bad case) require a nearby context word.

WHAT THIS DOES NOT DO
---------------------
Input only, per the sprint scope. A tool result can still carry the real value
back into the model's context — restoring a token for a lookup necessarily means
the lookup's ANSWER contains real data. Closing that needs output screening,
which is tracked separately.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field

# Per-turn token -> original value. A ContextVar so concurrent turns keep their
# own mapping instead of racing with one another.
_pii_map: ContextVar[dict | None] = ContextVar("ai_pii_map", default=None)

# Whether screening is on for the turn currently running. Set from the agent's
# configuration so the Chat Message hook makes the same call as the entry
# point — otherwise an agent with screening switched off would still have its
# transcript redacted.
_pii_on: ContextVar[bool] = ContextVar("ai_pii_on", default=True)

# Tokens look like [CIVIL_ID_1]. Deliberately bracketed and upper-case so they
# are visually obvious in a transcript and cheap to find again.
_TOKEN_RE = re.compile(r"\[([A-Z_]+)_(\d+)\]")


# ── Validators ──────────────────────────────────────────────────────────────
def _luhn_ok(digits: str) -> bool:
	"""Standard Luhn check for payment cards."""
	total, alt = 0, False
	for ch in reversed(digits):
		if not ch.isdigit():
			return False
		d = int(ch)
		if alt:
			d *= 2
			if d > 9:
				d -= 9
		total += d
		alt = not alt
	return total % 10 == 0


def _kuwait_civil_id_ok(value: str) -> bool:
	"""Kuwait Civil ID checksum.

	12 digits: century marker, YYMMDD, serial, then a weighted check digit
	(weights 2,1,6,3,7,9,10,5,8,4,2; sum mod 11; check = 11 - remainder).
	Without this, ``\\b[123]\\d{11}\\b`` would flag any 12-digit number — an
	order reference, a phone with a country code, a timestamp.
	"""
	if len(value) != 12 or not value.isdigit():
		return False
	weights = (2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
	total = sum(int(value[i]) * weights[i] for i in range(11))
	remainder = total % 11
	check = 11 - remainder
	return check == int(value[11])


def _always(value: str) -> bool:
	return True


# ── Detectors ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Detector:
	"""One PII pattern.

	label     — token prefix, e.g. CIVIL_ID -> [CIVIL_ID_1]
	pattern   — compiled regex; group(0) is the value replaced
	validator — arithmetic or structural check applied to the match
	context   — when set, the match only counts if one of these words appears
	            within `window` characters. Used where the shape alone is too
	            weak to stand on its own.
	"""

	label: str
	pattern: re.Pattern
	validator: object = _always
	context: tuple = ()
	window: int = 40

	def confirm(self, text: str, match: re.Match) -> bool:
		value = match.group(0)
		if not self.validator(re.sub(r"[\s-]", "", value)):
			return False
		if not self.context:
			return True
		start = max(0, match.start() - self.window)
		nearby = text[start : match.end() + self.window].lower()
		return any(word in nearby for word in self.context)


DETECTORS: tuple = (
	# Kuwait Civil ID — checksum-verified, so no context word needed.
	Detector(
		label="CIVIL_ID",
		pattern=re.compile(r"\b[123]\d{11}\b"),
		validator=_kuwait_civil_id_ok,
	),
	# Payment cards — Luhn-verified.
	Detector(
		label="CARD",
		pattern=re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
		validator=_luhn_ok,
	),
	# IBAN — country code + check digits + BBAN. Kuwait is KW + 28.
	Detector(
		label="IBAN",
		pattern=re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
	),
	Detector(
		label="EMAIL",
		pattern=re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"),
	),
	# Kuwait mobile: 8 digits starting 5/6/9, optionally +965. A bare 8-digit
	# run is common in ordinary text, so an explicit +965 is matched first and
	# the bare form requires a context word.
	Detector(
		label="PHONE",
		pattern=re.compile(r"\+?965[\s-]?[569]\d{7}\b"),
	),
	Detector(
		label="PHONE",
		pattern=re.compile(r"\b[569]\d{7}\b"),
		context=("phone", "mobile", "contact", "call", "whatsapp", "tel", "number"),
	),
	# Passport / work permit / visa numbers. Shape alone (letters + digits)
	# collides with order refs, part numbers and doc ids, so a context word is
	# required — this is the detector most likely to misfire otherwise.
	Detector(
		label="PASSPORT",
		pattern=re.compile(r"\b[A-Z]{1,2}\d{6,8}\b"),
		context=("passport", "visa", "work permit", "permit", "travel document",
		         "residency", "iqama"),
	),
)


# ── Redaction ───────────────────────────────────────────────────────────────
@dataclass
class RedactionResult:
	text: str
	mapping: dict = field(default_factory=dict)   # token -> original value
	counts: dict = field(default_factory=dict)    # label -> how many redacted
	enabled: bool = True                          # was screening on for this turn

	@property
	def redacted(self) -> bool:
		return bool(self.mapping)

	def summary(self) -> str:
		"""Loggable description that names the TYPES found, never the values."""
		return ", ".join(f"{n}x {label}" for label, n in sorted(self.counts.items()))


def redact(text: str) -> RedactionResult:
	"""Replace detected PII in ``text`` with stable tokens.

	The same value appearing twice gets the same token, so the model can still
	reason about "the two mentions of that ID are the same person".
	"""
	if not text or not isinstance(text, str):
		return RedactionResult(text=text or "")

	mapping: dict = {}
	by_value: dict = {}
	counts: dict = {}
	result = text

	for detector in DETECTORS:
		# Re-scan the partially redacted text each time so a later detector
		# cannot match inside a token another detector already inserted.
		out, cursor = [], 0
		for match in detector.pattern.finditer(result):
			if not detector.confirm(result, match):
				continue
			value = match.group(0)
			token = by_value.get(value)
			if token is None:
				counts[detector.label] = counts.get(detector.label, 0) + 1
				token = f"[{detector.label}_{counts[detector.label]}]"
				by_value[value] = token
				mapping[token] = value
			out.append(result[cursor : match.start()])
			out.append(token)
			cursor = match.end()
		out.append(result[cursor:])
		result = "".join(out)

	return RedactionResult(text=result, mapping=mapping, counts=counts)


def restore(text: str, mapping: dict | None = None) -> str:
	"""Swap tokens back for their original values.

	Used at the tool boundary so a lookup keyed on a redacted value still
	resolves. Falls back to the current turn's mapping when none is passed.
	"""
	if not text or not isinstance(text, str):
		return text
	mapping = mapping if mapping is not None else (current_mapping() or {})
	if not mapping or "[" not in text:
		return text
	for token, value in mapping.items():
		text = text.replace(token, value)
	return text


def restore_arguments(arguments):
	"""Recursively restore tokens anywhere in a tool-call argument payload.

	The model may put a token in a top-level string, inside a filters dict, or
	in a list — mirroring how the tool-policy scanner walks the same payload.
	"""
	mapping = current_mapping()
	if not mapping:
		return arguments

	def walk(value, depth=0):
		if depth > 6:
			return value
		if isinstance(value, str):
			return restore(value, mapping)
		if isinstance(value, dict):
			return {k: walk(v, depth + 1) for k, v in value.items()}
		if isinstance(value, list):
			return [walk(v, depth + 1) for v in value]
		if isinstance(value, tuple):
			return tuple(walk(v, depth + 1) for v in value)
		return value

	return walk(arguments)


def contains_token(text: str) -> bool:
	return bool(text) and bool(_TOKEN_RE.search(str(text)))


def wrap_tool(fn):
	"""Wrap a tool callable so token arguments arrive as real values.

	Applied by ToolSpec.__post_init__, which covers every tool the system
	builds — shape tools, pooled tools, and the ToolSpecs assembled inside
	Server Script bodies.
	"""

	def wrapped(**kwargs):
		return fn(**restore_arguments(kwargs))

	wrapped.__pii_wrapped__ = fn
	wrapped.__name__ = getattr(fn, "__name__", "tool")
	wrapped.__doc__ = getattr(fn, "__doc__", None)
	return wrapped


# ── Per-turn state ──────────────────────────────────────────────────────────
def begin_turn(result: "RedactionResult", enabled: bool = True):
	"""Publish this turn's token mapping and screening state.

	Returns an opaque handle to pass to :func:`end_turn`.
	"""
	# Always a dict, never None — ``mapping is not None`` is what marks a turn
	# as active, which is how merge_mapping avoids stranding a mapping outside
	# any turn (see there).
	return (
		_pii_map.set(dict(result.mapping or {})),
		_pii_on.set(bool(enabled)),
	)


def end_turn(handle) -> None:
	"""Drop the turn's mapping.

	The mapping must not outlive the turn — a leaked mapping would let a later,
	unrelated turn restore tokens it never created.
	"""
	map_token, on_token = handle
	for var, token in ((_pii_map, map_token), (_pii_on, on_token)):
		try:
			var.reset(token)
		except (ValueError, LookupError):
			var.set(None if var is _pii_map else True)


def screening_on() -> bool:
	return _pii_on.get()


def merge_mapping(mapping: dict) -> None:
	"""Add tokens to the mapping of the turn currently running.

	The Chat Message hook calls this so a value redacted at storage time is
	still resolvable when the agent calls a tool with the token.

	It deliberately does NOT create a mapping when no turn is active. Doing so
	would strand the mapping in the surrounding context with no ``end_turn`` to
	clear it — a mapping that outlives its turn is exactly what this module is
	meant to prevent. Nothing is lost: a message persisted outside a turn is
	re-screened by ``screen_input`` when the turn does start, and ``redact`` is
	deterministic, so the same text yields the same tokens.
	"""
	current = _pii_map.get()
	if not mapping or current is None:
		return
	current.update(mapping)


def current_mapping() -> dict | None:
	return _pii_map.get()


# ── Entry point used by invoke_agent ────────────────────────────────────────
def screen_input(text: str, agent_config=None) -> RedactionResult:
	"""Screen one user message. Returns the text to use downstream.

	``agent_config`` may be the resolved config dict (preferred — no extra
	query) or an AI Agent Configuration name.

	Never raises: a failure here must not stop a user talking to an agent, so a
	broken detector degrades to passing the text through unchanged and logging.
	That is the opposite of the tool-policy interceptor's fail-closed stance,
	and deliberately so — this control protects data in transit, it does not
	authorise an action, so failing closed would deny service for no safety gain.
	"""
	import frappe

	try:
		if not _screening_enabled(agent_config):
			return RedactionResult(text=text or "", enabled=False)
		result = redact(text)
		if result.redacted:
			label = agent_config.get("agent_id") if isinstance(agent_config, dict) else agent_config
			frappe.logger("pii").info(f"PII screened for agent={label or '-'}: {result.summary()}")
		return result
	except Exception:
		try:
			frappe.log_error(
				title="PII screening failed — text passed through unchanged",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return RedactionResult(text=text or "")


def screen_chat_message(doc, method=None):
	"""``before_insert`` on Chat Message — the transcript never stores raw PII.

	This is not belt-and-braces on top of ``screen_input``; it is load-bearing.
	Every map-driven agent's "Save User Message" script does::

	    user_text = msg_doc.text or user_text

	i.e. it re-reads the stored Chat Message and prefers it over the payload.
	Redacting only the in-flight message would therefore be undone for all
	seven map-driven agents — the redaction has to reach the stored row.

	It also stands on its own merit: a Civil ID sitting in ``Chat Message.text``
	is readable by anyone with access to the conversation, long after the turn.

	Because ``redact`` is deterministic, the token this produces is identical to
	the one ``screen_input`` produced for the same text, so the two paths agree.
	"""
	import frappe

	try:
		if getattr(doc, "message_type", None) != "User" or not screening_on():
			return
		result = redact(doc.text or "")
		if not result.redacted:
			return
		doc.text = result.text
		# Publish for this turn so a tool call can still resolve the token even
		# when the message was persisted outside an invoke_agent call.
		merge_mapping(result.mapping)
		frappe.logger("pii").info(
			f"PII screened in Chat Message for {doc.get('conversation') or '-'}: {result.summary()}"
		)
	except Exception:
		try:
			frappe.log_error(
				title="PII screening failed on Chat Message",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass


def _screening_enabled(agent_config) -> bool:
	"""On unless an agent explicitly opts out.

	The escape hatch exists because a screen that cannot be turned off gets
	worked around instead of reported when it misfires. It defaults to on, so
	an agent created before this field existed is screened.
	"""
	import frappe

	if not agent_config:
		return True
	if isinstance(agent_config, dict):
		return (agent_config.get("pii_screening") or "Enabled") != "Disabled"
	try:
		value = frappe.db.get_value("AI Agent Configuration", agent_config, "pii_screening")
		return (value or "Enabled") != "Disabled"
	except Exception:
		return True
