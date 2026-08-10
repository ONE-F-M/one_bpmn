# Copyright (c) 2026, one-fm and contributors
"""
WI-001840 AC2: tell every agent, once, that tool output is data.

The markers added in ``security/provenance.py`` are only half the control — a
delimiter the model was never told the meaning of buys nothing. This puts the
other half where WI-001639 said behaviour belongs: the agent's frozen static
context, as a Guard Rail ROW rather than a line of Python, so a site can reword
it, disable it for one agent, or tighten it after a bad week without a deploy.

Idempotent and non-destructive. An agent that already carries the rail is left
exactly as it is, including one where an admin has edited the wording or turned
it off — re-running must never quietly undo somebody's decision.
"""

import frappe

from one_bpmn.security.provenance import GUARD_RAIL_TEXT

# Enough of the text to recognise the rail again after someone has reworded it.
# Matching on the full string would re-add the rail every time an admin edited a
# word of it, which is the one thing this patch must not do.
#
# Bare token, no angle brackets: the field escapes markup on save, so a
# bracketed fingerprint would never match what actually came back and every
# migrate would bolt on another copy.
_FINGERPRINT = "tool_result"


def execute():
	names = frappe.get_all("AI Agent Configuration", pluck="name")
	added = 0

	for name in names:
		try:
			existing = frappe.get_all(
				"AI Agent Guard Rail",
				filters={"parent": name, "parenttype": "AI Agent Configuration"},
				fields=["guardrail"],
			)
			if any(_FINGERPRINT in (row.guardrail or "") for row in existing):
				continue

			doc = frappe.get_doc("AI Agent Configuration", name)
			doc.append("guardrails", {
				"guardrail": GUARD_RAIL_TEXT,
				"category": "Safety",
				"enabled": 1,
			})
			# The rail is a prompt-layer addition; it must not drag an agent
			# through provider validation or trip go-live checks on save.
			doc.flags.ignore_validate_update_after_submit = True
			doc.save(ignore_permissions=True)
			added += 1
		except Exception:
			# One unsaveable agent must not stop the rest getting the rail.
			frappe.log_error(
				title=f"Could not seed tool-result guard rail on {name}",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()
	print(f"Tool-result guard rail: added to {added} of {len(names)} agent configurations")
