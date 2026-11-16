"""
Move the freeze thresholds from Processa Settings onto each agent.

The throttle moved in ``move_rate_limit_to_agents``; this finishes the job. How
many blocked attempts an agent tolerates before freezing a conversation belongs
with it for the same reason the throttle does: an agent that fields adversarial
traffic all day should not freeze users at the same threshold as one that never
sees any, and the only way to loosen it for the first was to loosen it for
everybody.

``lock_release_roles`` stays site-wide and is untouched. Who may RELEASE a
freeze is a statement about roles on this site; it means nothing per agent.

Same shape, and the same trap, as the throttle patch. Frappe stamps a new
field's DEFAULT onto every existing row as it adds the column, so by the time
this runs no agent has a blank to fill — they all read 3-in-3600s whatever the
site was actually doing. A "fill only what is empty" rule would migrate nothing
while silently changing behaviour, which is exactly what happened the first time
round. Nobody can have chosen a per-agent value before the field existed, so on
this one run the site's answer wins outright.

Values come straight out of ``tabSingles``: a Single keeps them as rows there,
so they survive the fields being dropped from the doctype, whereas the document
would no longer have the attributes at all.
"""

import frappe

FREEZE_FIELDS = ("lock_after_blocks", "lock_block_window_seconds")


def _site_values() -> dict:
	out = {}
	try:
		rows = frappe.db.sql(
			"""SELECT field, value FROM `tabSingles`
			   WHERE doctype = 'Processa Settings' AND field IN %(fields)s""",
			{"fields": FREEZE_FIELDS},
			as_dict=True,
		)
		for row in rows:
			if row.value not in (None, ""):
				out[row.field] = row.value
	except Exception:
		frappe.log_error(
			title="Could not read the old site freeze thresholds; agents keep the defaults",
			message=frappe.get_traceback(),
		)
	return out


def execute():
	if not frappe.db.has_column("AI Agent Configuration", "lock_after_blocks"):
		return

	site = _site_values()
	if not site:
		print("Per-agent freeze: no site values to migrate; agents keep the defaults")
		return

	moved = 0
	for name in frappe.get_all("AI Agent Configuration", pluck="name"):
		# db_set, not save(): carrying a value across is not a change of intent,
		# and saving would drag every agent through its validation — live
		# provider calls and go-live checks included.
		frappe.db.set_value("AI Agent Configuration", name, dict(site), update_modified=False)
		moved += 1

	frappe.db.commit()
	print(f"Per-agent freeze: carried the site thresholds {site} onto {moved} agent(s)")
