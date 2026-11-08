# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Clear engine_in_progress on instances untouched for 20 minutes, longer than any engine pass can run."""

import frappe
from frappe.utils import add_to_date, now_datetime


def execute():
	cutoff = add_to_date(now_datetime(), minutes=-20)
	stale = frappe.get_all(
		"BPMN Process Instance",
		filters={"engine_in_progress": 1, "modified": ["<", cutoff]},
		pluck="name",
	)
	for name in stale:
		frappe.db.set_value(
			"BPMN Process Instance", name, "engine_in_progress", 0, update_modified=False
		)
