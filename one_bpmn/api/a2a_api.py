# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A protocol HTTP surface (WI-001931 / WI-001932).

Discovery is deliberately guest-readable — the spec expects an
unauthenticated card fetch — and deliberately unable to distinguish
"no such agent" from "agent not exposed": both are the same 404.

There is no /.well-known/ route in v1: this is a multi-agent site and
Frappe reserves that path for the web router, so the card URL is this
documented /api/method address instead.
"""

from __future__ import annotations

import frappe

from one_bpmn.agents.a2a.card import build_agent_card


@frappe.whitelist(allow_guest=True, methods=["GET"])
def agent_card(agent_id: str) -> dict:
	"""The public Agent Card for one exposed agent (WI-001931)."""
	card = build_agent_card(agent_id)
	if card is None:
		raise frappe.DoesNotExistError
	return card
