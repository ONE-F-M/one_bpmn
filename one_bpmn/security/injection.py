# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Run the injection rule pack over a message and record what fires (WI-001967).

RECORD-ONLY, DELIBERATELY
-------------------------
This observes; it does not intervene. The text is never altered and the turn is
never stopped, even for a rule whose declared intent is Block. Deciding what a
match should *do* — refuse, strip, escalate — is 15.1 / WI-001840, and getting
that wrong is far more damaging than being late to it: a screen that blocks real
work gets switched off, and then nothing is watched at all.

What it buys today is the dataset. Every match becomes an AI Security Event with
the rule, its type, the signature that matched, the agent and the conversation —
so by the time 15.1 chooses a policy, it can be chosen against real traffic
instead of guesses.

HONEST ABOUT THE ACTION
-----------------------
The event records the action actually TAKEN, not the rule's ambition. A Block
rule that fired while this module is record-only is written as ``Flag`` with its
declared intent kept in ``detail``. Recording "Block" for something that was not
blocked would make the log lie, and an audit log that lies is worse than none.
"""

from __future__ import annotations

import frappe


def screen_for_injection(
	text: str,
	*,
	boundary: str = "input",
	agent_configuration: str | None = None,
	conversation: str | None = None,
	run: str | None = None,
	bpmn_id: str | None = None,
) -> list[dict]:
	"""Record an event for every enabled rule matching ``text``.

	Returns the rules that fired (for callers and tests); the text itself is
	returned to nobody because it is never changed.

	Never raises. Screening is observation layered onto a live conversation — if
	the pack is unreadable or a write fails, the turn carries on exactly as it
	would have without it.
	"""
	if not text or not isinstance(text, str):
		return []

	try:
		from one_bpmn.one_bpmn.doctype.ai_injection_pattern.ai_injection_pattern import (
			active_patterns,
			compile_rule,
		)
		from one_bpmn.security.events import record_event

		fired = []
		for rule in active_patterns(boundary):
			matcher = compile_rule(rule)
			if not matcher or not matcher.search(text):
				continue

			declared = rule.get("action") or "Flag"
			# Nothing is enforced here, so the strongest thing that actually
			# happened is that the turn was surfaced for review.
			taken = "Log" if declared == "Log" else "Flag"
			detail = f"matched {rule['pattern_name']} ({rule.get('source_taxonomy') or '—'})"
			if declared != taken:
				detail += f"; rule intent {declared}, not enforced (15.1)"

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
			fired.append(rule)

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
