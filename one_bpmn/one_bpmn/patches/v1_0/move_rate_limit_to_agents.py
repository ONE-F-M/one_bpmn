"""
Move the message throttle from Processa Settings onto each agent.

One number for the whole site could not be right for all of them: a limit that
suits a chat assistant throttles a batch agent to a standstill, and the only way
to unblock the batch agent was to raise the ceiling for everybody. The throttle
is now a property of the agent.

The FREEZE stays site-wide and is untouched — "how many blocked attempts before
we contain someone" and "who may let them back in" are a site's security
posture, not a per-agent tuning knob.

WHY THE OLD VALUES ARE COPIED FORWARD

Whatever the site is running today is what it should keep running tomorrow. This
site, for instance, has the throttle switched OFF with a 3-in-180s limit behind
it; letting every agent silently jump to the doctype default of 20-in-60s would
turn an upgrade into a behaviour change nobody asked for. So the site values are
read first and stamped onto every agent.

Read straight out of `tabSingles` rather than through the document. A Single
keeps its values as rows there, so they survive the fields being dropped from
the doctype — but `get_cached_doc` would return a document that no longer has
the attributes, and the numbers would be lost exactly when they are needed.

WHY IT OVERWRITES RATHER THAN FILLING BLANKS

Frappe stamps a new field's DEFAULT onto every existing row as it adds the
column, so by the time this runs no agent has a blank to fill — they all read
20-in-60s whatever the site was actually doing. A "only fill what is empty"
rule therefore migrates nothing, which is how the first version of this patch
reported "0 agents" while quietly switching the throttle ON for a site that
had it off.

Nobody can have chosen a per-agent value before the field existed, so on this
one run there is no considered decision to protect and the site's answer wins.
A patch executes once; anyone who tunes an agent afterwards keeps their value.
"""

import frappe

THROTTLE_FIELDS = ("rate_limit_enabled", "rate_limit_messages", "rate_limit_window_seconds")


def _site_values() -> dict:
	"""The old Processa Settings throttle, straight from the Singles table."""
	out = {}
	try:
		rows = frappe.db.sql(
			"""SELECT field, value FROM `tabSingles`
			   WHERE doctype = 'Processa Settings' AND field IN %(fields)s""",
			{"fields": THROTTLE_FIELDS},
			as_dict=True,
		)
		for row in rows:
			if row.value not in (None, ""):
				out[row.field] = row.value
	except Exception:
		frappe.log_error(
			title="Could not read the old site throttle; agents keep the doctype defaults",
			message=frappe.get_traceback(),
		)
	return out


def execute():
	if not frappe.db.has_column("AI Agent Configuration", "rate_limit_messages"):
		return

	site = _site_values()
	if not site:
		# Nothing configured site-wide, so the doctype defaults already say the
		# same thing. Nothing to carry forward.
		print("Per-agent throttle: no site values to migrate; agents keep the defaults")
		return

	moved = 0
	for name in frappe.get_all("AI Agent Configuration", pluck="name"):
		# db_set, not save(): this is carrying a value across, not a change of
		# intent, and saving would drag every agent through its validation —
		# live provider calls and go-live checks included.
		frappe.db.set_value("AI Agent Configuration", name, dict(site), update_modified=False)
		moved += 1

	frappe.db.commit()
	print(f"Per-agent throttle: carried the site settings {site} onto {moved} agent(s)")
