# Copyright (c) 2026, one-fm and contributors
"""LuCrusher's phase tables told it to re-send the draft it was confirming.

The earlier patch (lucrusher_scan_digest_and_short_confirmations) added a
"Confirming a draft" section that says a confirmation carries only intent and
response. The seeded system prompt still carried three older lines in its
phase tables that said the opposite:

    User approves -> intent "TOPOLOGY_CONFIRMED", topology=<approved unchanged>.
    User approves -> intent "MIGRATION_TASKS_CONFIRMED", migration_tasks=<approved>.
    User approves -> intent "PROSALLY_PROMPT_CONFIRMED", prosally_prompts=<approved>.

Given both, the model followed the phase table. On staging run j7hmopv4il the
confirmation call carried the 1,412-character topology again and cost 626
completion tokens for a four-line reply. The three lines are rewritten so the
phase tables and the confirmation section say the same thing.

Sites whose prompt no longer carries the phase tables (the BA site trimmed its
copy by hand) are left untouched. Idempotent: each line is replaced only while
its old form is present.
"""

import frappe

_AGENT_ID = "lucrusher_agent"

# (old line, new line); the arrow and bullet characters match the seeded text.
_REWRITES = (
	(
		'  • User approves → intent "TOPOLOGY_CONFIRMED", topology=<approved unchanged>.',
		'  • User approves → intent "TOPOLOGY_CONFIRMED" with intent and response only; '
		"the platform keeps the approved topology, so do not send it again.",
	),
	(
		'  • User approves → intent "MIGRATION_TASKS_CONFIRMED", migration_tasks=<approved>.',
		'  • User approves → intent "MIGRATION_TASKS_CONFIRMED" with intent and response only; '
		"the platform keeps the approved tasks, so do not send them again.",
	),
	(
		'  • User approves → intent "PROSALLY_PROMPT_CONFIRMED", prosally_prompts=<approved>.',
		'  • User approves → intent "PROSALLY_PROMPT_CONFIRMED" with intent and response only; '
		"the platform keeps the approved prompts, so do not send them again.",
	),
)


def rewrite_confirmation_lines(prompt: str) -> tuple[str, bool]:
	"""The prompt edit as a pure function of its text. Returns the new text and
	whether anything changed; each line is replaced once, only where present."""
	prompt = prompt or ""
	changed = False
	for old, new in _REWRITES:
		if old in prompt:
			prompt = prompt.replace(old, new, 1)
			changed = True
	return prompt, changed


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	updated, changed = rewrite_confirmation_lines(prompt)
	if not changed:
		return
	frappe.db.set_value(
		"AI Agent Configuration", name, "system_prompt", updated, update_modified=False
	)
	print(f"lucrusher_confirmations_carry_no_draft: {name} confirms without re-sending the draft")
