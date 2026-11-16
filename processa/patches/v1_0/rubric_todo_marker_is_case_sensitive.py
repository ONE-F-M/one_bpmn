# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Stop the rubrics flagging Frappe's own ToDo DocType as a leaked marker.

The "nothing leaks" rule bans a stray ``TODO`` or ``FIXME`` in an answer, and
carried a leading ``(?i)`` that applied to every alternative in it. So it also
matched **ToDo** — the DocType — and an Orchestrator answer correctly reporting
"a pre-existing issue with the ToDo doctype" was marked as leaking.

Measured against the BA site's 76 Orchestrator answers: 6 would fail the old
rule, and only 3 of those deserve it (an unrendered ``{{ work_item_brief }}``,
which is the bug the rule exists to catch). The other 3 are this false positive.

The fix scopes case-insensitivity to the parts that need it — a traceback may
be printed either way — and leaves TODO/FIXME case-sensitive, which is how the
markers are written and how the DocType is not.
"""

import frappe

OLD = (
	r"(?i)^(?![\s\S]*(?:traceback \(most recent call last\)|frappe\.exceptions"
	r"|\bTODO\b|\bFIXME\b|\{\{\s*\w+\s*\}\}))[\s\S]*$"
)
NEW = (
	r"^(?![\s\S]*(?:(?i:traceback \(most recent call last\)|frappe\.exceptions)"
	r"|\bTODO\b|\bFIXME\b|\{\{\s*\w+\s*\}\}))[\s\S]*$"
)


def execute():
	suites = frappe.get_all("AI Eval Suite", filters={"suite_type": "Online Rubric"}, pluck="name")
	if not suites:
		return

	cases = frappe.get_all("AI Eval Case", filters={"suite": ["in", suites]}, pluck="name")
	if not cases:
		return

	rows = frappe.get_all(
		"AI Eval Assertion",
		filters={"parenttype": "AI Eval Case", "parent": ["in", cases], "value": OLD},
		pluck="name",
	)
	for row in rows:
		frappe.db.set_value("AI Eval Assertion", row, "value", NEW, update_modified=False)

	if rows:
		frappe.db.commit()
		print(f"rubric_todo_marker_is_case_sensitive: corrected {len(rows)} rule(s)")
