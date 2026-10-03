"""Docu's naming skill teaches a counter in braces, the only form a format: rule fills."""

import frappe

SKILL = "doctype-naming"
OLD = (
	'- `"format:INSP-.#####"`: a coded id with an auto-incrementing counter (the `.#####`). Prefer this when '
	"the person wants a reference number. The prefix is theirs; ask nothing, use the letters they used."
)
NEW = (
	'- `"format:INSP-{#####}"`: a coded id with an auto-incrementing counter (the `{#####}`). Prefer this when '
	"the person wants a reference number. The prefix is theirs; ask nothing, use the letters they used. "
	'A format: rule fills only what is in braces, so the counter must be in braces: `"format:INSP-.#####"` '
	"names every record `INSP-.#####`."
)


def execute():
	body = frappe.db.get_value("AI Skill", SKILL, "body") or ""
	if OLD in body:
		frappe.db.set_value("AI Skill", SKILL, "body", body.replace(OLD, NEW, 1))
