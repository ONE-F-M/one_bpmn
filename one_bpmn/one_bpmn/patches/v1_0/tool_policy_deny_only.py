# Copyright (c) 2026, one-fm and contributors
"""WI-001645: "Require Human Approval" is gone; every rule refuses.

The action Select no longer offers it, so a row still carrying that label cannot
be saved from the form and reads as an option that no longer exists. Converting
them is not a downgrade in strictness — refusing is the stricter reading, and
there is no longer anywhere for an approval to park.

The interceptor is safe either way: _ACTION_BY_LABEL maps anything it does not
recognise to DENY. This patch exists so the stored data says what is actually
happening, rather than leaving a row that claims to ask a person and does not.

Approver values are cleared with the same update. Their columns are dropped by
the doctype sync; clearing them first keeps the audit trail honest if a site
runs this patch before the sync lands.
"""

import frappe


def execute():
	if not frappe.db.table_exists("AI Tool Policy Rule"):
		return

	rows = frappe.get_all(
		"AI Tool Policy Rule",
		filters={"action": "Require Human Approval"},
		pluck="name",
	)
	if not rows:
		return

	columns = {c.Field for c in frappe.db.sql("desc `tabAI Tool Policy Rule`", as_dict=True)}
	for name in rows:
		update = {"action": "Deny"}
		for field in ("approver_user", "approver_role"):
			if field in columns:
				update[field] = None
		frappe.db.set_value("AI Tool Policy Rule", name, update, update_modified=False)

	frappe.logger("one_bpmn").info(
		f"tool_policy_deny_only: converted {len(rows)} approval rule(s) to Deny — {rows}"
	)

	# Rules are cached and read on every tool call; without this the old action
	# would keep being served until the cache expired.
	try:
		from one_bpmn.security.tool_policy import clear_rule_cache

		clear_rule_cache()
	except Exception:
		pass
