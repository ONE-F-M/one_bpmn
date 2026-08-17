# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Run the injection rule pack over a message, record what fires, and act (WI-001840).

WHAT CHANGED
------------
15.2 built this as record-only on purpose: it watched, and it never intervened,
because choosing what a match should DO is far more damaging to get wrong than to
get late. A screen that blocks real work gets switched off, and then nothing is
watched at all. That decision is now made, and it is made as CONFIGURATION rather
than in code — per agent, defaulting to the mildest setting that still defuses an
attack.

THE THREE ACTIONS
-----------------
``Log``    record it, send the message through untouched. For watching a new
           agent before tightening.
``Flag``   record it, remove the matched phrase, let the turn continue on what is
           left. The default. The attack is defused and the user does not lose
           their request — which matters, because most of what this pack fires on
           will be an ordinary message that happens to contain an imperative.
``Block``  record it and refuse the turn, telling the user why.

Flag is the default deliberately. Block is the setting that generates complaints
and gets a control switched off site-wide; Flag removes the dangerous span and
leaves the rest of the sentence doing its job.

HONEST ABOUT THE ACTION
-----------------------
The event records the action actually TAKEN, not the rule's ambition, and not the
agent's configured preference. A Block-intent rule on a Log-mode agent is written
as ``Log``, with the rule's declared intent kept in ``detail``. An audit log that
overstates what happened is worse than none.

FAILS OPEN
----------
Every path here is wrapped. If the pack is unreadable, a rule fails to compile, or
the event write fails, the turn proceeds exactly as it would have without any
screening. A screening fault must never be the reason someone cannot talk to an
agent.
"""

from __future__ import annotations

import frappe
from frappe import _

from one_bpmn.security.refusal import AgentRefusal


class InjectionBlocked(AgentRefusal):
	"""The message was refused because a rule fired and the agent is set to Block.

	An AgentRefusal, so the engine treats it as a decision and lets the reason
	reach the user instead of halting the process instance.
	"""


# Shown to the user on Block. Deliberately says what happened and what to do, and
# deliberately does NOT quote the matched phrase back — echoing the payload into
# the chat surface is how a blocked attempt still gets rendered somewhere.
BLOCK_MESSAGE = (
	"This message looks like an attempt to change how the assistant behaves, so it "
	"was not sent. If this was a normal request, rephrase it and try again."
)


def screening_enabled(agent_config) -> bool:
	"""On unless an agent explicitly opts out.

	Mirrors the PII escape hatch, and for the same reason: a screen that cannot
	be turned off gets worked around instead of reported when it misfires. An
	agent created before the field existed is screened.

	The setting is read from the RECORD, not off the dict the caller passed.
	The dict branch used to read ``agent_config["injection_screening"]`` — and
	the resolved config from get_agent_config does not carry that key, so the
	lookup always missed, always defaulted to "Enabled", and the switch did
	nothing on the live chat path. It read as working because a direct call
	passing the record NAME took the other branch and behaved correctly.
	resolve_action, immediately below, already resolved the name properly; this
	now does the same thing, which is also why the two can no longer disagree
	about which agent they are talking about.
	"""
	if not agent_config:
		return True
	try:
		if isinstance(agent_config, dict) and agent_config.get("injection_screening"):
			# An explicit value on the payload wins — the agent-creation path
			# passes a not-yet-saved config this way.
			return agent_config["injection_screening"] != "Disabled"

		from one_bpmn.security.pii import _config_name

		name = _config_name(agent_config)
		if not name:
			return True
		value = frappe.db.get_value("AI Agent Configuration", name, "injection_screening")
		return (value or "Enabled") != "Disabled"
	except Exception:
		# Fail towards screening: a lookup failure must not silently exempt an
		# agent from the control.
		return True


def resolve_action(agent_config) -> str:
	"""The agent's configured action, defaulting to Flag.

	Flag for an agent that predates the field and for one whose value cannot be
	read. It defuses without refusing, so an upgrade cannot turn into an outage
	the way a Block default could — while a Log default would leave a live
	instruction-override reaching the model with nothing but a log line.
	"""
	from one_bpmn.security.pii import _config_name

	name = _config_name(agent_config)
	value = None
	if name:
		try:
			value = frappe.db.get_value("AI Agent Configuration", name, "injection_action")
		except Exception:
			value = None
	return value if value in ("Log", "Flag", "Block") else "Flag"


def screen_for_injection(
	text: str,
	*,
	boundary: str = "input",
	agent_configuration: str | None = None,
	conversation: str | None = None,
	run: str | None = None,
	bpmn_id: str | None = None,
	action: str | None = None,
) -> list[dict]:
	"""Record an event for every enabled rule matching ``text``.

	Returns the rules that fired, each carrying the character spans it matched
	under ``_spans`` so a caller applying Flag knows exactly what to remove.
	This function still only OBSERVES — it never edits the text and never
	raises. Acting on the result is :func:`screen_input`.

	``action`` is the outcome the caller is about to apply, recorded on the
	event so the log states what actually happened. Omitted, it defaults to
	Flag, which is what an unconfigured agent gets.

	Never raises. Screening is observation layered onto a live conversation — if
	the pack is unreadable or a write fails, the turn carries on exactly as it
	would have without it.
	"""
	if not text or not isinstance(text, str):
		return []

	taken = action if action in ("Log", "Flag", "Block") else "Flag"

	try:
		from one_bpmn.one_bpmn.doctype.ai_injection_pattern.ai_injection_pattern import (
			active_patterns,
			compile_rule,
		)
		from one_bpmn.security.events import record_event

		fired = []
		for rule in active_patterns(boundary):
			matcher = compile_rule(rule)
			if not matcher:
				continue
			spans = [m.span() for m in matcher.finditer(text)]
			if not spans:
				continue

			declared = rule.get("action") or "Flag"
			detail = f"matched {rule['pattern_name']} ({rule.get('source_taxonomy') or '—'})"
			# The rule's ambition and the agent's setting can disagree in either
			# direction. Say so, so a reviewer reading the log can tell a
			# deliberately relaxed agent from a rule that never wanted to block.
			if declared != taken:
				detail += f"; rule intent {declared}, agent set to {taken}"

			record_event(
				boundary=boundary,
				stage="injection",
				action=taken,
				content=text,
				rule=rule["name"],
				rule_type=rule.get("pattern_type"),
				matched_pattern=rule.get("pattern"),
				severity=rule.get("severity"),
				agent_configuration=agent_configuration,
				conversation=conversation,
				run=run,
				bpmn_id=bpmn_id,
				detail=detail,
			)
			fired.append({**rule, "_spans": spans})

		if fired:
			frappe.logger("injection").info(
				f"injection rules fired for agent={agent_configuration or '-'}: "
				+ ", ".join(r["pattern_name"] for r in fired)
			)
		return fired
	except Exception:
		try:
			frappe.log_error(
				title="Injection screening failed — turn continued unscreened",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return []


def _strip(text: str, fired: list[dict]) -> str:
	"""Remove every matched span, leaving a visible marker in its place.

	Removed rather than tokenised: a PII token has to survive the round trip so
	the tool call still resolves, but an injection payload has no legitimate
	downstream use. The marker is left so the model can see the sentence was
	edited instead of silently reading a mangled one, and so a reviewer reading
	the transcript can tell the difference between a user who wrote a strange
	sentence and one whose sentence was cut.

	Spans are merged and applied right-to-left, so overlapping matches from two
	rules cannot corrupt each other's offsets.
	"""
	spans = sorted((s for rule in fired for s in rule.get("_spans") or ()), key=lambda s: s[0])
	if not spans:
		return text

	merged: list[list[int]] = []
	for start, end in spans:
		if merged and start <= merged[-1][1]:
			merged[-1][1] = max(merged[-1][1], end)
		else:
			merged.append([start, end])

	out = text
	for start, end in reversed(merged):
		out = out[:start] + "[removed]" + out[end:]
	return " ".join(out.split())


class InjectionScreeningResult:
	"""What screening decided about one message.

	``text`` is what should now be sent to the model — identical to the input
	unless the action was Flag and something matched.
	"""

	def __init__(self, text: str, fired: list[dict], action: str, enabled: bool):
		self.text = text
		self.fired = fired
		self.action = action
		self.enabled = enabled

	@property
	def changed(self) -> bool:
		return bool(self.fired) and self.action == "Flag"

	def summary(self) -> str:
		if not self.fired:
			return "no injection rules fired"
		names = ", ".join(r["pattern_name"] for r in self.fired)
		return f"{self.action}: {names}"


def screen_input(
	text: str,
	agent_config=None,
	*,
	boundary: str = "input",
	conversation: str | None = None,
	run: str | None = None,
	bpmn_id: str | None = None,
	raise_on_block: bool = True,
) -> InjectionScreeningResult:
	"""Screen a message and APPLY the agent's configured action (WI-001840).

	Raises :class:`InjectionBlocked` when the agent is set to Block and a rule
	fired — the one case where this function does not return. That exception is
	an AgentRefusal, so the engine reports it to the user as a decision rather
	than halting the process instance.

	``raise_on_block=False`` returns the Block verdict instead of raising, for
	callers with no user waiting on the other end. A background memory write has
	nobody to refuse, so it inspects ``action`` and drops the write instead.

	Every other path returns, including every failure path. If anything inside
	screening breaks, the original text comes back unchanged and the turn
	proceeds: a fault in a security control must not be the reason someone
	cannot talk to an agent.
	"""
	if not text or not isinstance(text, str):
		return InjectionScreeningResult(text, [], "Log", True)

	try:
		if not screening_enabled(agent_config):
			return InjectionScreeningResult(text, [], "Log", False)

		from one_bpmn.security.pii import _config_name

		action = resolve_action(agent_config)
		fired = screen_for_injection(
			text,
			boundary=boundary,
			agent_configuration=_config_name(agent_config),
			conversation=conversation,
			run=run,
			bpmn_id=bpmn_id,
			action=action,
		)
	except Exception:
		try:
			frappe.log_error(
				title="Injection screening failed — turn continued unscreened",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return InjectionScreeningResult(text, [], "Log", True)

	if not fired:
		return InjectionScreeningResult(text, [], action, True)

	# Raised OUTSIDE the try above on purpose: a Block is the intended outcome,
	# not an error, and must not be swallowed by the fail-open handler.
	if action == "Block":
		if raise_on_block:
			raise InjectionBlocked(BLOCK_MESSAGE)
		return InjectionScreeningResult(text, fired, action, True)

	if action == "Flag":
		try:
			return InjectionScreeningResult(_strip(text, fired), fired, action, True)
		except Exception:
			frappe.log_error(
				title="Injection strip failed — message sent unchanged",
				message=frappe.get_traceback(),
			)
			return InjectionScreeningResult(text, fired, "Log", True)

	return InjectionScreeningResult(text, fired, action, True)
