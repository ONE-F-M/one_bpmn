# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Conformance validator for chat agents.

A passing adversarial suite proves the agent resisted the attacks it was shown.
It does not prove the shipped agent still screens anything. This closes that gap:
no conforming agent can skip the screen.

WHY THIS NO LONGER LOOKS INSIDE THE MAP
---------------------------------------
It originally required a screening stage as an element in the agent's map,
marked ``spiffworkflow:aiScreeningStage``. The reasoning was sound at the time:
the creation process CLONED a template map per agent, so a clone could have the
stage deleted and that agent would silently stop being screened.

Two things then made that check false rather than strict:

  * The template and the cloning were retired. A map is now a designer's own
    link, and a chat agent may legitimately have no map at all (the Direct API
    path), so "the cloned map" it guarded no longer exists.
  * Screening was never built as a map step. It runs centrally, on every turn of
    every agent: ``security.pii.screen_chat_message`` on Chat Message insert, and
    ``security.injection.screen_for_injection`` inside the invocation path. No map
    on this site has ever carried the marker.

So the check was hunting for a declaration that nothing produces, while the thing
it was meant to guarantee was already true everywhere — failing every agent, and
teaching a reader that the gate is noise.

WHAT "CONFORMING" MEANS NOW
---------------------------
That the screen an agent's messages pass through is actually armed:

  * the Chat Message screening hook is registered, so stored messages are
    screened — this one is load-bearing, because every map-driven agent re-reads
    the stored row; and
  * the injection pack has at least one enabled rule, since a pack with nothing
    in it matches nothing and would pass silently.

Both fail CLOSED. A map, when one is linked, must still be a chat map — an agent
with a chat mode label pointed at a business process can never receive a turn.
"""

from __future__ import annotations

import frappe
from frappe import _


def screening_status() -> dict:
	"""Is the platform's message screening armed? {"ok": bool, "errors": [...]}.

	Fails closed on every uncertain answer: a screen that cannot be shown to be
	wired is treated as absent, because this authorises a release.
	"""
	errors = []

	try:
		from one_bpmn import hooks

		# before_insert is a STRING when one handler is wired and a LIST when
		# several are. Both forms are normal Frappe, and the substring test that
		# worked on the string form silently became an element-equality test when
		# the output screen was added alongside this one — the list holds the full
		# dotted path, which never equals the bare function name, so the gate
		# reported PII screening as absent while it was running fine.
		hooked = ((hooks.doc_events or {}).get("Chat Message") or {}).get("before_insert") or ""
		handlers = [hooked] if isinstance(hooked, str) else list(hooked or [])
		if not any("screen_chat_message" in str(h) for h in handlers):
			errors.append(
				_(
					"Chat Message screening is not wired: no before_insert hook runs "
					"security.pii.screen_chat_message, so stored messages reach the agent "
					"unscreened."
				)
			)
	except Exception:
		errors.append(_("The screening hook could not be read, so it cannot be shown to be active."))

	try:
		if not frappe.db.count("AI Injection Pattern", {"enabled": 1}):
			errors.append(
				_(
					"The injection pattern pack has no enabled rules, so screening would "
					"match nothing. Enable the seeded rules under AI Injection Pattern."
				)
			)
	except Exception:
		errors.append(_("The injection pattern pack could not be read, so screening cannot be verified."))

	return {"ok": not errors, "errors": errors}


def validate_chat_map(model_name: str) -> dict:
	"""Is this chat agent conforming? {"ok": bool, "errors": [...]}.

	Named for the map it used to inspect; it now verifies the screen an agent's
	messages actually pass through, and checks the map only for the thing a map
	can still get wrong. A chat agent with NO map is fine — that is the Direct
	API path — so a missing link is no longer an error.
	"""
	errors = list(screening_status()["errors"])

	if model_name:
		if not frappe.db.exists("BPMN Process Model", model_name):
			errors.append(_("Process map '{0}' does not exist.").format(model_name))
		else:
			xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml") or ""
			if not xml.strip():
				errors.append(_("Process map '{0}' is empty.").format(model_name))
			elif 'triggerDoctype="Chat Conversation"' not in xml:
				# The same rule validate_agent_config applies, said here too: a
				# chat agent pointed at a business process can never take a turn.
				errors.append(
					_(
						"Process map '{0}' is not a chat map — it has no start event on Chat "
						"Conversation insert, so this agent can never receive a message."
					).format(model_name)
				)

	return {"ok": not errors, "errors": errors}
