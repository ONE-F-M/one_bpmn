# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Release engine gates leaked by the missing inline release.

Between PR #425 (which made complete_task work again on version-15) and the
finally-release fix shipped alongside this patch, every successful Confirm on
an AI-less process model set ``engine_in_progress = 1`` and nothing ever
cleared it — permanently blocking all further actions on the instance with
"Instance is processing — an engine pass … is currently running."

This one-time repair clears the flag on every instance where it is provably
stale: set, but untouched for longer than the AI job timeout (600s). No
legitimate engine pass survives that long — inline passes live inside a web
request, and parked AI jobs are killed by the queue timeout. The margin is
doubled for safety.
"""

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
	frappe.db.commit()
