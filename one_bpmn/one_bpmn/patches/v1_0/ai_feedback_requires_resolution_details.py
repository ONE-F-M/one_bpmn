"""Fixed feedback carries resolution details: existing Fixed records get a note, and the Mark Fixed script refuses none.

The script edit is skipped when the script already has the check, and logged and left alone when its text has moved.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

BACKFILL = "Resolved before resolution details were recorded."
MARKER = "resolution_details"
MARK_FIXED = (
	'frappe.db.set_value(\n\t"AI Response Feedback",\n',
	'if not (doc.resolution_details or "").strip():\n'
	'\tfrappe.throw("Add the resolution details on the feedback before marking it Fixed.")\n'
	'frappe.db.set_value(\n\t"AI Response Feedback",\n',
)


def execute():
	backfill_fixed_records()
	require_resolution_in_mark_fixed()


def backfill_fixed_records():
	frappe.db.set_value(
		"AI Response Feedback",
		{"status": "Fixed", "resolution_details": ["is", "not set"]},
		"resolution_details",
		BACKFILL,
		update_modified=False,
	)


def require_resolution_in_mark_fixed():
	name = frappe.db.get_value("Server Script", {"name": ["like", "AI Feedback%Mark Fixed"]}, "name")
	if name:
		apply_edits("Server Script", name, "script", (MARK_FIXED,), MARKER)
