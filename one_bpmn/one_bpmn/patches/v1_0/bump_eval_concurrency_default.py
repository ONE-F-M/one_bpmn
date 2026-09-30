"""
Eval concurrency's shipped default moves from 1 to 4: lanes now run one RQ job
each instead of one thread each, and a low default no longer buys any safety
that the per-lane timeout and the hard cap of 8 do not already provide.

A Single's schema default only fills a row that has never set the field.
Every site that installed before this change stored an explicit 1, and a
schema default change alone would never touch it. So this patch raises it
for exactly the sites that are still sitting on the old default \u2014 anyone who
deliberately chose a different value (0, 2, 8, ...) keeps their own choice.

Idempotent: re-running finds nothing left at 1 to bump.
"""

import frappe


def execute():
	if not frappe.db.has_column("Processa Settings", "eval_concurrency"):
		return

	current = frappe.db.get_single_value("Processa Settings", "eval_concurrency")
	if current == 1:
		frappe.db.set_single_value("Processa Settings", "eval_concurrency", 4)
		frappe.db.commit()
		print("Eval concurrency: raised Processa Settings.eval_concurrency from 1 to 4")
