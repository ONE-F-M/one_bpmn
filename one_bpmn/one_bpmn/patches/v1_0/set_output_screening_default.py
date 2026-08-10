"""
WI-001644: give every existing agent an explicit output screening mode.

A new field defaults only for rows created after it exists, so every agent that
predates it holds NULL. Screening still applies to them — ``_mode`` falls back to
Flag — but the fallback is invisible: the desk form and the Processa modal show
an empty control while the agent is, in fact, redacting. Someone reading the
configuration would conclude screening was off.

So the value is written rather than left to the fallback. Same behaviour, but
now it is visible, and switching an agent to Log or Block is an edit to
something that already has a value rather than a guess about what blank means.

Two cases are filled. NULL/empty, as above. And ``Log``, because the field
briefly shipped with Log as its default inside this same unmerged story — Frappe
backfills a new field's default onto existing rows, so a site that migrated that
commit holds Log on every agent as an artifact rather than a choice. Nobody
could have deliberately chosen Log before this patch runs, because the control
existed nowhere else. Anyone choosing Log AFTER it runs keeps it: a patch
executes once.

``Block`` is never touched — that is always a deliberate tightening. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.has_column("AI Agent Configuration", "output_screening_mode"):
		return

	agents = frappe.get_all(
		"AI Agent Configuration",
		filters={"output_screening_mode": ("in", ["", None, "Log"])},
		pluck="name",
	)
	for name in agents:
		# db_set, not doc.save(): this is a default being made explicit, not a
		# change of intent, and saving would fire the revalidation hook on every
		# agent on the site — live provider calls and all.
		frappe.db.set_value(
			"AI Agent Configuration", name, "output_screening_mode", "Flag", update_modified=False
		)

	if agents:
		frappe.db.commit()
		print(f"WI-001644: set output_screening_mode=Flag on {len(agents)} agent(s)")
