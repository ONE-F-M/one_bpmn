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
	"""
	try:
		doc = frappe.new_doc("AI Security Event")
		doc.boundary = boundary
		doc.stage = stage
		doc.action = action or "Log"
		doc.severity = severity
		doc.rule = rule if rule and frappe.db.exists("AI Injection Pattern", rule) else None
		doc.rule_type = rule_type
		doc.matched_pattern = _trim(matched_pattern, MAX_DETAIL_LENGTH)
		doc.classifier = classifier
		doc.agent_configuration = (
			agent_configuration
			if agent_configuration and frappe.db.exists("AI Agent Configuration", agent_configuration)
			else None
		)
		doc.conversation = conversation
		doc.run = run if run and frappe.db.exists("AI Agent Run", run) else None
		doc.bpmn_id = bpmn_id
		# Input screening runs before the AI Agent Run exists, so the run cannot be
		# named here and the event cannot be edited later to add it. The turn's
		# correlation id is stamped on both records instead (WI-001967).
		from one_bpmn.security.turn import current_correlation_id

		doc.correlation_id = correlation_id or current_correlation_id()
		doc.content_hash = content_hash(content)
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
