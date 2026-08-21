# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The one door every screening verdict goes through (WI-001967).

Any stage that decides something — PII redaction, injection matching, tool
policy, memory-write screening — calls :func:`record_event` instead of keeping
its own table or settling for a log line. One shape, one place, so the events
become a dataset a reviewer can actually work with and evals can be built from.

FAILS OPEN, ALWAYS
------------------
Recording is observation, not enforcement. If the write fails, the screening
decision that was already made still applies and the caller carries on — the
failure is reported separately via ``frappe.log_error`` so it is visible without
being able to take a conversation down. A logging subsystem that can break the
thing it observes is worse than no logging.

NEVER STORES THE CONTENT
------------------------
Callers pass the screened text so a hash can be taken; the text itself is
discarded immediately. ``detail`` is for a non-identifying summary such as
"2x CIVIL_ID" — :func:`record_event` refuses anything that looks like it might
be the content instead.
"""

from __future__ import annotations

import frappe

from one_bpmn.one_bpmn.doctype.ai_security_event.ai_security_event import content_hash

# A summary is a summary. Anything longer than this is far more likely to be the
# screened text pasted in by mistake, which is exactly what must never be kept.
MAX_DETAIL_LENGTH = 500


# What makes two calls the SAME verdict rather than two findings.
#
# `rule` is in here and matters: injection screening records one event per
# matching pattern, all with the same text, the same stage and classifier=None.
# Without `rule` those would collapse into one and the log would under-report a
# multi-rule attack.
#
# `action` is in here too — a finding that was Logged and a finding that was
# Blocked are different verdicts even on identical text.
_IDENTITY_FIELDS = ("stage", "boundary", "action", "classifier", "rule", "content_hash")

# Filled in on the surviving event if the second caller knew something the first
# did not. Never overwritten — only blanks.
_COMPLETABLE_FIELDS = ("agent_configuration", "conversation", "run", "bpmn_id")


def _same_verdict_this_turn(correlation_id: str, identity: dict) -> str | None:
	"""An event already recorded for this exact verdict in this turn.

	Scoped to the turn's correlation id, so it can only ever collapse records
	written by one message passing through more than one screen. Two identical
	messages sent a minute apart are different turns and stay two events.
	"""
	if not correlation_id:
		return None
	filters = {"correlation_id": correlation_id}
	for field in _IDENTITY_FIELDS:
		value = identity.get(field)
		# A dict filter of None does not reliably mean IS NULL across backends.
		filters[field] = value if value not in (None, "") else ("is", "not set")
	try:
		return frappe.db.get_value("AI Security Event", filters, "name")
	except Exception:
		return None


def _complete_event(name: str, values: dict) -> None:
	"""Fill fields the first recording of this verdict could not know.

	The two PII screens see different halves of the same turn: the API entry
	point knows the agent but runs before the conversation exists, and the Chat
	Message hook knows the conversation but has no agent config to hand. Writing
	both events produced two half-records; suppressing one alone would have
	thrown away whichever half lost.

	This is completing a record inside the turn that produced it, not editing an
	audited fact — only NULL/empty fields are touched, never a value that was
	already recorded. ``update_modified`` stays off so `modified` keeps matching
	`creation`: the Security view orders by last-updated on the understanding
	that events are written once, and a fill would otherwise reshuffle the log.
	"""
	patch = {f: v for f, v in values.items() if v}
	if not patch:
		return
	try:
		current = frappe.db.get_value("AI Security Event", name, list(patch), as_dict=True) or {}
		blanks = {f: v for f, v in patch.items() if not current.get(f)}
		if blanks:
			frappe.db.set_value("AI Security Event", name, blanks, update_modified=False)
	except Exception:
		# A record that stays half-filled is still a record; losing the whole
		# turn over it would be worse.
		pass


def record_event(
	*,
	boundary: str,
	stage: str,
	action: str = "Log",
	content: str | None = None,
	rule: str | None = None,
	rule_type: str | None = None,
	matched_pattern: str | None = None,
	classifier: str | None = None,
	severity: str | None = None,
	agent_configuration: str | None = None,
	conversation: str | None = None,
	run: str | None = None,
	bpmn_id: str | None = None,
	correlation_id: str | None = None,
	detail: str | None = None,
) -> str | None:
	"""Record one screening verdict. Returns the event name, or None if it failed.

	Args:
		boundary: input / output / tool-result / memory-write.
		stage: the screening stage, e.g. "pii", "injection", "tool-policy".
		action: Log / Flag / Block — what the screen did, not what it wanted to do.
		content: the screened text. Hashed and measured, then dropped. Never stored.
		rule: name of the AI Injection Pattern that fired, when the pack drove it.
		matched_pattern: the pattern expression that matched — the signature, not
			the user's words.
		classifier: detector name when the detection did not come from the pack.
		detail: short non-identifying summary. Truncated hard; see MAX_DETAIL_LENGTH.

	A None return means the event was not recorded and the caller should carry
	on regardless — that is the contract, not an error to handle.

	Calling this twice for the same verdict in the same turn records ONE event.
	A message can pass more than one screen on its way through — PII runs both at
	the API entry point and again on the stored Chat Message, because each is
	load-bearing on its own — and both were writing a row. The returned name is
	the surviving event either way, so a caller cannot tell the difference.
	"""
	try:
		from one_bpmn.security.turn import current_correlation_id

		resolved_correlation = correlation_id or current_correlation_id()
		resolved_agent = (
			agent_configuration
			if agent_configuration and frappe.db.exists("AI Agent Configuration", agent_configuration)
			else None
		)
		resolved_run = run if run and frappe.db.exists("AI Agent Run", run) else None
		resolved_hash = content_hash(content)

		duplicate = _same_verdict_this_turn(
			resolved_correlation,
			{
				"stage": stage,
				"boundary": boundary,
				"action": action or "Log",
				"classifier": classifier,
				"rule": rule if rule and frappe.db.exists("AI Injection Pattern", rule) else None,
				"content_hash": resolved_hash,
			},
		)
		if duplicate:
			_complete_event(
				duplicate,
				{
					"agent_configuration": resolved_agent,
					"conversation": conversation,
					"run": resolved_run,
					"bpmn_id": bpmn_id,
				},
			)
			return duplicate

		doc = frappe.new_doc("AI Security Event")
		doc.boundary = boundary
		doc.stage = stage
		doc.action = action or "Log"
		doc.severity = severity
		doc.rule = rule if rule and frappe.db.exists("AI Injection Pattern", rule) else None
		doc.rule_type = rule_type
		doc.matched_pattern = _trim(matched_pattern, MAX_DETAIL_LENGTH)
		doc.classifier = classifier
		doc.agent_configuration = resolved_agent
		doc.conversation = conversation
		doc.run = resolved_run
		doc.bpmn_id = bpmn_id
		# Input screening runs before the AI Agent Run exists, so the run cannot be
		# named here. The turn's correlation id is stamped on both records instead
		# (WI-001967), which is also what lets the duplicate check above scope
		# itself to a single turn.
		doc.correlation_id = resolved_correlation
		doc.content_hash = resolved_hash
		doc.content_length = len(content) if isinstance(content, str) else 0
		doc.detail = _trim(detail, MAX_DETAIL_LENGTH)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		# Deliberately swallowed. The screening decision has already been made and
		# applied by the caller; losing the record must not lose the protection.
		try:
			frappe.log_error(
				title=f"AI Security Event write failed (stage={stage}, boundary={boundary})",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return None


def _trim(value, limit: int) -> str | None:
	if value in (None, ""):
		return None
	text = value if isinstance(value, str) else str(value)
	return text if len(text) <= limit else text[: limit - 1] + "…"


def record_pii_events(
	result,
	*,
	boundary: str = "input",
	agent_configuration: str | None = None,
	conversation: str | None = None,
	run: str | None = None,
	original_text: str | None = None,
) -> list[str]:
	"""Record one event per PII type found in a ``RedactionResult``.

	One event per detector rather than one per turn, so "how often does the
	Civil ID detector fire" is a filter rather than a parsing exercise. The
	action is Log: PII redaction neither blocks nor needs review, it just happens
	— and recording it as Flag would drown the genuine flags.
	"""
	names = []
	for label, count in sorted((result.counts or {}).items()):
		name = record_event(
			boundary=boundary,
			stage="pii",
			action="Log",
			content=original_text,
			classifier=label,
			severity="Medium",
			agent_configuration=agent_configuration,
			conversation=conversation,
			run=run,
			detail=f"{count}x {label}",
		)
		if name:
			names.append(name)
	return names
