"""WI-000463: the Frontend Agent's "HOW THE FRONT END HERE IS WRITTEN" block becomes a skill.

seed_frontend_agent_config.py's system_prompt carries a fixed block of house-style
rules (frappe-ui components, Vue script-setup conventions, Tailwind tokens,
frappeRequest, desk-script conventions, file-size guidance) inline in the system
prompt, paid for on every single turn even though it only matters while the
agent is actually writing or editing front-end code. This patch moves that block
into an AI Skill ("Frontend House Style") the agent loads before writing or
editing a file, and replaces the block in the prompt with a short pointer plus
the load_skill instruction.

Idempotent: matches on the exact block seed_frontend_agent_config.py is known to
have written; a prompt already carrying the pointer, or one whose block has
already been hand-edited away, is left alone.
"""

import frappe

AGENT_ID = "frontend_agent"
SKILL_NAME = "frontend-house-style"

OLD_BLOCK = """HOW THE FRONT END HERE IS WRITTEN
- frappe-ui components rather than raw markup: Button, FormControl with type select, Dialog. A hand-rolled control re-implements focus, keyboard handling and dark mode, worse.
- Vue uses script setup. Prefer computed over methods, clean up listeners in onBeforeUnmount, never put v-if and v-for on one element, never write v-for without a key.
- Colours come from Tailwind tokens, never hex literals.
- Fetch data with frappeRequest. Do not introduce fetch or axios.
- Desk scripts use frappe.ui.form.on and match the siblings in their folder.
- Components here are already large. Leave a file the same size or smaller; past about three hundred lines of script, extract something instead."""

NEW_BLOCK = """HOW THE FRONT END HERE IS WRITTEN
Call load_skill with `frontend-house-style` before you write or edit any front-end file \u2014 it holds the component, Vue, styling and desk-script conventions this codebase follows."""

SKILL_DESCRIPTION = (
	"The house style this codebase's front end is written to: frappe-ui components over raw "
	"markup, Vue script-setup conventions, Tailwind tokens instead of hex literals, frappeRequest "
	"for data fetching, desk-script conventions, and a file-size guideline. Use this skill before "
	"writing or editing any Vue component, Frappe desk JavaScript file, or other front-end file. "
	"Do NOT use it for a purely backend Python change."
)

SKILL_BODY = """# Frontend house style

- frappe-ui components rather than raw markup: Button, FormControl with type select, Dialog. A hand-rolled control re-implements focus, keyboard handling and dark mode, worse.
- Vue uses script setup. Prefer computed over methods, clean up listeners in onBeforeUnmount, never put v-if and v-for on one element, never write v-for without a key.
- Colours come from Tailwind tokens, never hex literals.
- Fetch data with frappeRequest. Do not introduce fetch or axios.
- Desk scripts use frappe.ui.form.on and match the siblings in their folder.
- Components here are already large. Leave a file the same size or smaller; past about three hundred lines of script, extract something instead.
"""


def execute():
	_upsert_skill()

	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Agent Configuration", name)

	changed = False
	prompt = doc.system_prompt or ""
	if OLD_BLOCK in prompt and NEW_BLOCK not in prompt:
		doc.system_prompt = prompt.replace(OLD_BLOCK, NEW_BLOCK, 1)
		changed = True

	enabled = {row.skill for row in doc.enabled_skills}
	if SKILL_NAME not in enabled:
		doc.append("enabled_skills", {"skill": SKILL_NAME})
		changed = True

	if changed:
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)


def _upsert_skill():
	if frappe.db.exists("AI Skill", SKILL_NAME):
		existing = frappe.get_doc("AI Skill", SKILL_NAME)
		if (existing.description, existing.body, existing.status) == (
			SKILL_DESCRIPTION,
			SKILL_BODY,
			"Active",
		):
			return
		existing.description = SKILL_DESCRIPTION
		existing.body = SKILL_BODY
		existing.status = "Active"
		existing.save(ignore_permissions=True)
		return
	new = frappe.new_doc("AI Skill")
	new.skill_name = SKILL_NAME
	new.tier = "Draft-Only"
	new.description = SKILL_DESCRIPTION
	new.body = SKILL_BODY
	new.status = "Active"
	new.save(ignore_permissions=True)
