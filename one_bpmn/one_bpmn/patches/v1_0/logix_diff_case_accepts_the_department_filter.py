"""The Logix baseline's modify case accepts any added line that sets the department filter to Operations.

A filter written as ["like", "%Operations%"] is the same change as the exact match, so the diff check
looks for the department key and Operations on one added line. Only that assertion of that one case is
refreshed, and a second run changes nothing.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_baseline_suite as seed

MODIFY_CASE = "A change to the linked script comes back as a diff that keeps the rest"


def _is_diff_regex(value: str) -> bool:
	check = json.loads(value or "{}")
	return (check.get("tool"), check.get("path"), check.get("matcher")) == ("finalize", "diff", "regex")


def execute():
	suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name")
	name = suite and frappe.db.get_value("AI Eval Case", {"suite": suite, "title": MODIFY_CASE}, "name")
	if not name:
		return
	spec = next(c for c in seed.CASES if c["title"] == MODIFY_CASE)
	wanted = next(
		a["value"]
		for a in spec["assertions"]
		if a["assertion_type"] == "tool_artifact" and _is_diff_regex(a["value"])
	)
	case = frappe.get_doc("AI Eval Case", name)
	changed = False
	for row in case.assertions:
		if row.assertion_type == "tool_artifact" and _is_diff_regex(row.value) and row.value != wanted:
			row.value = wanted
			changed = True
	if changed:
		case.save(ignore_permissions=True)
