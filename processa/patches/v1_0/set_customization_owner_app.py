"""Point "Review Doctypes → Sync" at one_fm instead of upstream Frappe.

Sync grouped the changed doctypes by the app that OWNS each doctype and derived
that app's git remote. On this bench those remotes are the public upstream
projects — ``frappe/erpnext``, ``frappe/hrms``, ``frappe/helpdesk`` — not ONE-F-M
forks, and every one of one_fm's 108 customization modules targets a doctype
owned by one of them. So the feature aimed 100% of real customization PRs at a
repository the organisation does not control.

``customization_app`` fixes the routing, and its field default handles fresh
installs. A Single that already exists gets no default applied, though, so
without this patch every existing site keeps the old behaviour with an empty
field. Set it once.

Only fills a blank: a site that has deliberately chosen a different app keeps it.
"""

import frappe

DEFAULT_APP = "one_fm"


def execute():
	# NOT frappe.db.has_column: Processa Settings is a Single, so it has no table
	# of its own and has_column raises TableMissingError rather than returning
	# False. Under `bench migrate --skip-failing` that exception is swallowed and
	# the patch is still recorded as applied — it would never run again, and the
	# field would stay blank with nothing to show why.
	if not frappe.get_meta("Processa Settings").has_field("customization_app"):
		# The doctype JSON has not synced yet (a stale `modified` timestamp will
		# do it). Nothing to set; the next migrate that installs the field runs
		# this patch's entry only if it has not already been logged, so make the
		# absence loud rather than silently passing.
		frappe.log_error(
			title="set_customization_owner_app: field not installed",
			message=(
				"Processa Settings has no customization_app field, so the customization "
				"owner app was not set. Re-run this patch after the field installs, or set "
				"it by hand, or 'Review Doctypes → Sync' will keep targeting the doctype's "
				"owning app (upstream Frappe repositories for most doctypes)."
			),
		)
		return

	current = (frappe.db.get_single_value("Processa Settings", "customization_app") or "").strip()
	if current:
		return

	if DEFAULT_APP not in frappe.get_installed_apps():
		return

	frappe.db.set_single_value("Processa Settings", "customization_app", DEFAULT_APP)
	frappe.clear_cache(doctype="Processa Settings")
