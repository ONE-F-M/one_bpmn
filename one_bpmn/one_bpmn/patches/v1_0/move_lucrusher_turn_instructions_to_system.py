# Copyright (c) 2026, one-fm and contributors
"""LuCrusher paid for its own instructions on every turn.

The agent's "how to work this turn" block — 950 characters, identical every
turn — sat in the shape's ``aiUserPrompt``, so it was re-sent at full price with
each user message and made up most of that agent's per-turn user step. Stable
instructions belong in the system role, which the provider caches.

This moves the block into the linked configuration's system prompt, VERBATIM:
the assembler drops any block the system prompt already carries from the user
prompt, and it matches on the text itself, so an exact copy is what makes the
duplicate disappear without the diagram having to be re-exported.

Idempotent: the block is appended only while the system prompt lacks it.
"""

import frappe

_AGENT_ID = "lucrusher_agent"

_HEADING = "## Working a turn"

_BLOCK = (
	"Work this turn by calling tools, then ALWAYS finish by calling finalize "
	"exactly once — finalize is what the user actually sees, so a turn without "
	"it is a lost turn. Never answer in prose: your plain-text output is "
	"discarded. Ground every claim in a tool result; never invent process names, "
	"document contents or code paths. Call search_processes_on_production when "
	"the user names a process to look up, fetch_lucidchart_document when they "
	"supply a Lucidchart link or document id, and scan_codebase_for_process when "
	"they ask what code already implements the process. Do NOT re-run a tool the "
	"migration context above already reports as done. Topology, migration tasks "
	"and ProsAlly prompt blocks are your own analysis — pass them to finalize as "
	"its topology / migration_tasks / prosally_prompts arguments. Do not pass "
	"the Lucidchart document or the codebase scan to finalize: it reads the full "
	"tool results itself."
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _AGENT_ID}, "name")
	if not name:
		return

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if _BLOCK in prompt:
		return

	updated = f"{prompt.rstrip()}\n\n{_HEADING}\n{_BLOCK}\n" if prompt.strip() else f"{_HEADING}\n{_BLOCK}\n"
	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", updated, update_modified=False)
	print(f"move_lucrusher_turn_instructions_to_system: moved the turn instructions onto {name}")
