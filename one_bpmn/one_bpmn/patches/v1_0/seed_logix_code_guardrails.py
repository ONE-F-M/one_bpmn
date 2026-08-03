# Copyright (c) 2026, one-fm and contributors
"""Seed Logix's code-writing guard rails (WI-001639).

Logix is the agent that writes Server Scripts, so it is the first agent to get
real guard rails: keep files small, watch execution cost, watch token cost.
These are the three rules the story named.

Only the AI Agent Configuration is touched — the map and its Server Scripts
ship by Processa export/import, never by patch.

Idempotent: a rule already present (matched on its text) is left alone, so
re-running never duplicates rows and never overwrites an edit an author made
to the wording. Existing rows on the agent are preserved.
"""

import frappe

AGENT_ID = "logix_agent"

GUARDRAILS = [
	{
		"category": "Code Quality",
		"guardrail": (
			"Keep every script you write under 300 lines. If the logic does not fit, "
			"say so and propose splitting it rather than emitting a longer file."
		),
	},
	{
		"category": "Performance",
		"guardrail": (
			"Check the execution speed of what you write: no query inside a loop that "
			"could be a single bulk query, no full-table read where a filter would do. "
			"State the expected cost when the script touches more than a few hundred rows."
		),
	},
	{
		"category": "Cost & Tokens",
		"guardrail": (
			"Check token usage: do not echo an entire script back when a diff or the "
			"changed function would do, and never restate context the caller already sent."
		),
	},
]


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		print(f"seed_logix_code_guardrails: no agent '{AGENT_ID}' on this site — skipped")
		return

	doc = frappe.get_doc("AI Agent Configuration", name)
	existing = {(row.guardrail or "").strip() for row in (doc.guardrails or [])}

	added = 0
	for rule in GUARDRAILS:
		if rule["guardrail"].strip() in existing:
			continue
		doc.append("guardrails", {**rule, "enabled": 1})
		added += 1

	if not added:
		print("seed_logix_code_guardrails: already seeded — nothing to do")
		return

	# save() is safe here even though Logix is Live: the on-save revalidation
	# (which makes a live provider call and can park the agent) returns early
	# under frappe.flags.in_patch, so this cannot demote an agent on a site
	# whose credentials are not set up. on_update still clears the config cache.
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"seed_logix_code_guardrails: added {added} guard rail(s) to {name}")
