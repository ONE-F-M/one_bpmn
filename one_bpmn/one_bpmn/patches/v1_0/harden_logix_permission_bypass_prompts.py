# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Harden the Logix sub-prompts against permission-bypass / durability-override calls.

Symptom: Logix chat frequently ended a turn with
    "I was unable to generate a safe script after multiple attempts. Please
     rephrase your request to avoid forbidden operations ..."
The Error Log showed every failure was the same violation —
`Permission-bypass keyword 'ignore_permissions=...' is not allowed`. The
script_writer habitually emitted `doc.save(ignore_permissions=True)` /
`frappe.db.commit()`, which the security gate (one_bpmn/security/script_validator.py)
ALWAYS blocks. With only 2 regeneration retries the turn exhausted its budget and
returned the refusal (see the "Logix – Tool Finalize" stage).

The old prompts only mentioned `frappe.flags.ignore_permissions` in passing and
never named the actual offender (the `ignore_permissions=True` keyword argument),
nor told the model what to do instead. This patch:
  - script_writer: replaces rule 3 with an explicit, prominent prohibition of the
    always-blocked patterns plus the correct permission-respecting alternative.
  - script_reviewer: upgrades the security check to a MUST-fix that strips those
    patterns and returns a clean revised_script.

Runs AFTER add_logix_agent_tool_authoring (which produces the current prompt text
on fresh installs). Idempotent: it only rewrites a row when the old anchor is still
present and the hardened text is not, so a manual re-edit or a re-run is a no-op.
"""
import frappe

AGENT_ID = "logix_agent"

WRITER_OLD = "3. No raw SQL unless explicitly requested; never `frappe.set_user` or `frappe.flags.ignore_permissions` (the security gate rejects them)."
WRITER_NEW = (
	"3. **NEVER use permission-bypass or durability-override calls — the security gate ALWAYS rejects them, "
	"and after a couple of retries the whole turn fails with a \"could not generate a safe script\" refusal.** "
	"Do NOT emit ANY of these, in any form:\n"
	"   - the `ignore_permissions` keyword argument on ANY call: `doc.save(ignore_permissions=True)`, "
	"`.insert(ignore_permissions=True)`, `.submit(ignore_permissions=True)`, `.delete(ignore_permissions=True)`, "
	"`frappe.get_doc(...).insert(ignore_permissions=True)`, or the dict-unpacked `save(**{\"ignore_permissions\": True})`;\n"
	"   - `frappe.flags.ignore_permissions`, `frappe.set_user(...)`, `db_update(...)`, `add_roles(...)`;\n"
	"   - `frappe.db.commit()` / `frappe.db.rollback()` — the engine owns the transaction;\n"
	"   - raw destructive SQL (`frappe.db.sql` with DROP/TRUNCATE/ALTER/CREATE TABLE), and any raw SQL unless the user explicitly asks for it.\n"
	"   INSTEAD: just call `.save()` / `.insert()` / `.submit()` with NO permission keyword — the script already runs "
	"with the acting user's own permissions. If the request genuinely needs elevated writes, DO NOT bypass: for a "
	"script_task `frappe.throw(\"...\")` explaining the limitation; for an agent_tool set `result[\"error\"] = \"...\"`."
)

REVIEWER_OLD = "5. Security — no arbitrary exec, no hardcoded secrets, no unguarded frappe.db.sql, no frappe.set_user / ignore_permissions"
REVIEWER_NEW = (
	"5. Security — MUST fix (set approved=false and return a revised_script with the offending code removed/replaced). "
	"The pre-deployment gate ALWAYS blocks these, so leaving any in place fails the turn: the `ignore_permissions` keyword "
	"argument in ANY form (`.save(ignore_permissions=True)`, `.insert(ignore_permissions=True)`, `.submit(...)`, "
	"`save(**{\"ignore_permissions\": ...})`), `frappe.flags.ignore_permissions`, `frappe.set_user`, `db_update`, `add_roles`, "
	"`frappe.db.commit()`/`rollback()`, raw destructive SQL (DROP/TRUNCATE/ALTER/CREATE TABLE) or any unguarded/unrequested raw SQL, "
	"arbitrary exec/eval, and hardcoded secrets. Replace a bypassed write with a plain `.save()`/`.insert()` (no kwarg); if the "
	"intent truly requires a bypass, rewrite to `frappe.throw(...)` (script_task) or `result[\"error\"]=...` (agent_tool) instead."
)

# (sub_agent_id, old_anchor, new_text)
_REPLACEMENTS = (
	("script_writer", WRITER_OLD, WRITER_NEW),
	("script_reviewer", REVIEWER_OLD, REVIEWER_NEW),
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	doc = frappe.get_doc("AI Agent Configuration", name)

	updated = False
	for row in doc.sub_prompts:
		for sub_agent_id, old, new in _REPLACEMENTS:
			if row.sub_agent_id != sub_agent_id:
				continue
			text = row.prompt_text or ""
			# Idempotent: only act when the old rule is still there and the new
			# rule is not, so re-runs and manual re-edits are preserved.
			if new not in text and old in text:
				row.prompt_text = text.replace(old, new)
				updated = True

	if updated:
		doc.save(ignore_permissions=True)  # on_update clears agent_config:logix_agent cache
		frappe.db.commit()
