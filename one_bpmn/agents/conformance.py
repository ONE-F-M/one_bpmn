# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Conformance validator for chat-agent maps (WI-001969).

A passing adversarial suite proves the agent resisted the attacks it was shown.
It does not prove the shipped map still screens anything — an agent can pass its
suite and then go Live on a clone with the screening stage deleted. This closes
that gap: no conforming agent can skip the screen.

WHAT "CONFORMING" MEANS
-----------------------
A chat agent's map must contain a screening stage: an element the runtime
recognises as the point where an incoming message is screened before it reaches
the model. It is identified structurally rather than by position, so authors can
move it, rename its label, or wrap it in a subprocess without breaking
conformance:

  * an element carrying ``spiffworkflow:aiScreeningStage="true"``; or
  * an element whose id or name matches SCREENING_ID_HINTS, which covers the
    maps authored before the marker existed.

THE MARKER IS THE CONTRACT
--------------------------
``aiScreeningStage`` is defined HERE, by this story, because the gate needs
something to check and the template that will carry it is authored elsewhere.
The story that builds the screening stage should set this marker on it. Until a
template exists, ``validate_chat_map`` reports a clear, actionable failure
rather than passing an unscreened agent by default — the direction a security
gate should fail.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

# The attribute that marks an element as the screening stage. Structural, so the
# check survives renaming and repositioning.
SCREENING_MARKER = "aiScreeningStage"

# Fallback recognition for maps authored before the marker existed. Matched
# case-insensitively against an element's id and name.
SCREENING_ID_HINTS = ("screen_input", "screening", "screen_message", "input_screen")


def _elements(xml: str):
	"""Yield (tag, attributes-string) for every BPMN element in the XML."""
	for match in re.finditer(r"<bpmn:(\w+)\b([^>]*)>", xml or ""):
		yield match.group(1), match.group(2)


def has_screening_stage(xml: str) -> bool:
	"""True when the map contains something the runtime will screen with."""
	if not xml:
		return False

	for _tag, attrs in _elements(xml):
		if f"spiffworkflow:{SCREENING_MARKER}" in attrs:
			value = re.search(rf'spiffworkflow:{SCREENING_MARKER}="([^"]*)"', attrs)
			if value and value.group(1).strip().lower() in ("1", "true", "yes", "on", "enabled"):
				return True

		identifiers = " ".join(
			m.group(1).lower()
			for m in re.finditer(r'\b(?:id|name)="([^"]*)"', attrs)
		)
		if any(hint in identifiers for hint in SCREENING_ID_HINTS):
			return True

	return False


def validate_chat_map(model_name: str) -> dict:
	"""Is this chat agent's map conforming? {"ok": bool, "errors": [...]}.

	Fails closed on every uncertain answer — a map that cannot be read cannot be
	shown to screen, and a release gate should refuse rather than assume.
	"""
	errors = []

	if not model_name:
		return {
			"ok": False,
			"errors": [
				_("The agent has no process map linked, so its screening stage cannot be verified.")
			],
		}

	if not frappe.db.exists("BPMN Process Model", model_name):
		return {"ok": False, "errors": [_("Process map '{0}' does not exist.").format(model_name)]}

	xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml") or ""
	if not xml.strip():
		errors.append(_("Process map '{0}' is empty.").format(model_name))
	elif not has_screening_stage(xml):
		errors.append(
			_(
				"Process map '{0}' has no screening stage. A chat agent's map must contain an "
				"element marked spiffworkflow:{1}=\"true\" so every incoming message is screened "
				"before it reaches the model."
			).format(model_name, SCREENING_MARKER)
		)

	return {"ok": not errors, "errors": errors}


@frappe.whitelist()
def conformance_status(agent: str) -> dict:
	"""Whitelisted conformance read for one agent, for a UI to show up front."""
	frappe.has_permission("AI Agent Configuration", "read", throw=True)
	model = frappe.db.get_value("AI Agent Configuration", agent, "process_model")
	result = validate_chat_map(model)
	result["agent"] = agent
	result["process_model"] = model
	return result
