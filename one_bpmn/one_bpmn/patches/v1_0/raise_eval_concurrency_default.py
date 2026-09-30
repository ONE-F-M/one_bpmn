"""
Eval runner parallelism: raise the site-wide default for how many eval lanes
may run side by side from 1 to 4.

A Select/Int field's default only applies to a row created after the default
changes; Processa Settings is a Single, so its one existing row keeps whatever
value it already holds until something writes to it. Left alone, every site
that installed this app before the default moved would keep running eval
suites one case at a time forever, even though the new default is 4.

Only sites still sitting on the OLD default of 1 are touched. A value a site
already set deliberately \u2014 including a deliberate 1, or an 8 someone dialled
up \u2014 is left exactly as it is: this patch raises a default, it does not
impose a policy.
"""

import frappe


def execute():
	if not frappe.db.has_column("Processa Settings", "eval_concurrency"):
		return

	current = frappe.db.get_single_value("Processa Settings", "eval_concurrency")
	if current == 1:
		frappe.db.set_single_value(
			"Processa Settings", "eval_concurrency", 4, update_modified=False
		)
		frappe.db.commit()
		print("WI-000467: raised Processa Settings.eval_concurrency from 1 to 4")
