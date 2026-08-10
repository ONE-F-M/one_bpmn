# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Output screening: what the agent says, checked before anyone reads it.

Input screening protects the model from the user. This protects the user — and
the record — from the model. Three things must not leave an agent:

* **Credentials.** An agent that can read a config file or a traceback can
  repeat an API key into a chat bubble that is then stored forever.
* **Personal data.** Reusing the input detectors, so "what counts as PII" has
  one definition and the two directions cannot disagree.
* **The agent's own instructions.** A successful prompt-extraction attack ends
  with the system prompt in the response. Matching is FUZZY because a model
  paraphrases when it leaks — an exact-match check catches only the clumsiest
  attempt and gives false comfort for the rest.

THE ACTION IS THE AGENT'S TO CHOOSE

``output_screening_mode`` is Log, Flag or Block, and it defaults to Log:

* **Flag** (the default) — recorded, offending text replaced with a token. The
  reply still reads and the reader can see something was removed. Chosen as the
  default because a leak that is merely *logged* has still reached the user, and
  redaction stops that without ever refusing to answer.
* **Log** — recorded, response untouched. Observation, for watching a new agent
  before tightening.
* **Block** — recorded, whole response replaced. For an agent where a leak is
  worse than silence.

WHY IT FAILS OPEN

A broken detector must not stop an agent answering. This control protects data
in transit; it does not authorise an action, so failing closed would deny
service for no safety gain — the same reasoning as the input side, and the
opposite of the release gate, which does authorise something.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from one_bpmn.security.pii import DETECTORS, Detector

# A leak is a stretch of the instructions, not a turn of phrase. Below this many
# characters an overlap is a coincidence — "You are a helpful assistant" appears
# in half the prompts ever written and matching it would flag every polite reply.
MIN_LEAK_CHARS = 60

# How close a paraphrase has to be. Tuned by hand against real agent replies:
# lower and ordinary answers that quote a guard rail back at the user trip it,
# higher and a light paraphrase of the system prompt walks straight through.
LEAK_RATIO = 0.72

# Credentials are their own family, separate from the PII detectors, because
# they are not personal data and a site may reasonably screen one and not the
# other. Patterns are deliberately shape-based — a specific provider's prefix
# ages badly, while "a long opaque token introduced by a key-ish word" does not.
CREDENTIAL_DETECTORS: tuple = (
	Detector(
		label="PRIVATE_KEY",
		pattern=re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]{0,4000}?-----END[A-Z ]*PRIVATE KEY-----"),
	),
	Detector(
		label="API_KEY",
		# Provider-shaped keys: a recognisable prefix followed by a long opaque body.
		pattern=re.compile(r"\b(?:sk|pk|rk|api|key)[-_][A-Za-z0-9_\-]{16,}\b"),
	),
	Detector(
		label="BEARER_TOKEN",
		pattern=re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._\-]{20,}\b"),
	),
	Detector(
		label="JWT",
		pattern=re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
	),
	Detector(
		label="SECRET_ASSIGNMENT",
		# key = value in config/env shape. The VALUE is what gets replaced, so the
		# reply can still say which setting was involved without leaking it.
		pattern=re.compile(
			r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|access[_-]?key|private[_-]?key)"
			r"\s*[:=]\s*[\"']?([A-Za-z0-9/_+\-\.]{8,})[\"']?"
		),
	),
)


@dataclass
class OutputScreeningResult:
	"""What screening decided about one response."""

	text: str                                   # what should actually be sent
	original: str = ""
	counts: dict = field(default_factory=dict)  # label -> how many
	action: str = "Log"                         # what the agent's mode asked for
	blocked: bool = False
	enabled: bool = True

	@property
	def findings(self) -> bool:
		return bool(self.counts)

	@property
	def changed(self) -> bool:
		return self.text != self.original

	def summary(self) -> str:
		"""Names the TYPES found, never the values — this goes into logs."""
		return ", ".join(f"{n}x {label}" for label, n in sorted(self.counts.items()))


BLOCKED_REPLACEMENT = (
	"This response was withheld because it contained information that must not "
	"leave the agent — a credential, personal data, or the agent's own instructions. "
	"The attempt has been recorded for review."
)


def _mode(agent_config) -> str:
	"""The agent's configured action, defaulting to Flag.

	Flag for an agent that predates the field and for one whose value cannot be
	read. It redacts but never refuses, so an upgrade cannot turn into an outage
	the way a Block default could — while a Log default would leave a real leak
	reaching the user with nothing but a log line to show for it.
	"""
	import frappe

	from one_bpmn.security.pii import _config_name

	# The resolved config dict from get_agent_config is CURATED — it carries
	# agent_id but neither `name` nor the screening fields — so reading the mode
	# off it silently yields None and the screen quietly does nothing. Resolve to
	# the record and read the field, whichever form the caller passed.
	name = _config_name(agent_config)
	value = None
	if name:
		try:
			value = frappe.db.get_value("AI Agent Configuration", name, "output_screening_mode")
		except Exception:
			value = None
	return value if value in ("Log", "Flag", "Block") else "Flag"


def _static_context_for(agent_config) -> str:
	"""The agent's frozen instructions — what a leak would be a leak OF.

	Returns "" when it cannot be read, which turns the leak check off for that
	turn rather than comparing against nothing and matching everything.
	"""
	import frappe

	try:
		from one_bpmn.agents.context_assembler import (
			build_static_context_from_config,
			load_agent_behaviour,
		)
		from one_bpmn.security.pii import _config_name

		# Same reason as _mode: the passed dict may not name the record, and the
		# instructions have to come from the record to be worth comparing against.
		name = _config_name(agent_config)
		if not name:
			return ""

		config = frappe.get_cached_doc("AI Agent Configuration", name).as_dict()
		behaviour = load_agent_behaviour(name) or {}
		merged = dict(config)
		for key in ("examples", "guardrails"):
			if behaviour.get(key):
				merged[key] = behaviour[key]
		return build_static_context_from_config(merged) or ""
	except Exception:
		return ""


def _leak_spans(text: str, static_context: str) -> list:
	"""Stretches of ``text`` that fuzzily reproduce the agent's instructions.

	Compared line by line rather than as one blob: a response that leaks three
	scattered rules should be caught, and a whole-document ratio would average
	that away to nothing against a long reply.
	"""
	if not text or not static_context:
		return []

	reference = [
		line.strip()
		for line in re.split(r"[\n\r]+", static_context)
		if len(line.strip()) >= MIN_LEAK_CHARS
	]
	if not reference:
		return []

	spans = []
	for candidate in re.split(r"(?<=[.!?])\s+|[\n\r]+", text):
		stripped = candidate.strip()
		if len(stripped) < MIN_LEAK_CHARS:
			continue
		for line in reference:
			if difflib.SequenceMatcher(None, stripped.lower(), line.lower()).ratio() >= LEAK_RATIO:
				spans.append(stripped)
				break
	return spans


def screen_output(text: str, agent_config=None, conversation: str = None) -> OutputScreeningResult:
	"""Screen one agent response. Returns what should actually be sent.

	Never raises. A failure returns the response untouched and logs — see the
	module docstring for why this control fails open.
	"""
	import frappe

	original = text if isinstance(text, str) else ""
	try:
		if not original.strip():
			return OutputScreeningResult(text=original, original=original)

		mode = _mode(agent_config)
		counts: dict = {}
		result = original

		# 1. Credentials, then 2. PII — both replaced in place, so the sentence
		#    around them survives and the reply still makes sense.
		for detector in (*CREDENTIAL_DETECTORS, *DETECTORS):
			def _swap(match, det=detector):
				# confirm() applies the detector's own validator AND its context
				# window, so a shape that is only PII near the right words stays
				# subject to that rule here too.
				if not det.confirm(result_before, match):
					return match.group(0)
				# A capture group means the pattern deliberately isolated the secret
				# from its label; replace only that part so "api_key = [REDACTED]"
				# still tells the reader which setting was involved.
				value = match.group(1) if match.groups() else match.group(0)
				counts[det.label] = counts.get(det.label, 0) + 1
				return match.group(0).replace(value, f"[{det.label}_REDACTED]")

			result_before = result
			result = detector.pattern.sub(_swap, result)

		# 3. The agent's own instructions coming back out.
		for span in _leak_spans(result, _static_context_for(agent_config)):
			counts["PROMPT_LEAK"] = counts.get("PROMPT_LEAK", 0) + 1
			result = result.replace(span, "[INSTRUCTIONS_REDACTED]")

		if not counts:
			return OutputScreeningResult(text=original, original=original, action=mode)

		# Log observes and changes nothing; Flag keeps the redacted text; Block
		# withholds the response entirely.
		if mode == "Log":
			sent, blocked = original, False
		elif mode == "Block":
			sent, blocked = BLOCKED_REPLACEMENT, True
		else:
			sent, blocked = result, False

		out = OutputScreeningResult(
			text=sent, original=original, counts=counts, action=mode, blocked=blocked
		)
		_record(out, agent_config, conversation=conversation)
		frappe.logger("pii").info(
			f"Output screening ({mode}) for agent="
			f"{(agent_config.get('agent_id') if isinstance(agent_config, dict) else agent_config) or '-'}: "
			f"{out.summary()}"
		)
		return out
	except Exception:
		try:
			frappe.log_error(
				title="Output screening failed — response sent unchanged",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return OutputScreeningResult(text=original, original=original)


def _record(result: OutputScreeningResult, agent_config, conversation: str = None) -> None:
	"""One AI Security Event per finding TYPE, on the output boundary.

	Per type rather than per occurrence: three redacted emails in one reply is
	one fact about that reply, and three rows would drown the log a reviewer is
	supposed to read.
	"""
	try:
		from one_bpmn.security.events import record_event
		from one_bpmn.security.pii import _config_name

		# Block is the only action that stopped anything; Flag altered the text
		# but the turn continued, which is what "Flag" means in the event log.
		action = "Block" if result.blocked else ("Flag" if result.action == "Flag" else "Log")
		for label, count in sorted(result.counts.items()):
			record_event(
				boundary="output",
				stage="output-screening",
				action=action,
				severity="High" if label == "PROMPT_LEAK" or label.endswith("KEY") else "Medium",
				classifier=label,
				agent_configuration=_config_name(agent_config),
				conversation=conversation,
				content=result.original,
				detail=f"{count}x {label} in the agent's response; mode={result.action}",
			)
	except Exception:
		pass


def screen_chat_response(doc, method=None):
	"""``before_insert`` on a Bot Chat Message — the transcript never stores a leak.

	The counterpart to the input hook, and load-bearing for the same reason: a
	map-driven agent writes its reply as a Chat Message and the surface reads it
	back from there, so screening only the in-flight string would be undone by
	the stored row. It is also the one boundary every agent passes, whatever
	path produced the answer.
	"""
	import frappe

	if getattr(doc, "message_type", None) != "Bot":
		return

	try:
		from one_bpmn.security.pii import _agent_for_conversation

		agent_name, _ = _agent_for_conversation(doc.get("conversation"))
		if not agent_name:
			# Internal plumbing (memory distillation writes its own conversation)
			# is not an agent talking to a person, and screening it would record
			# the system's own bookkeeping as a leak.
			return

		# screen_output records the event itself — passing the conversation here
		# rather than recording again is what keeps one finding to one row.
		result = screen_output(doc.text or "", agent_name, conversation=doc.get("conversation"))
		if result.changed:
			doc.text = result.text
	except Exception:
		try:
			frappe.log_error(
				title="Output screening on Chat Message failed — response stored unchanged",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
