"""Point connector-handler pull requests at the app that owns the connector layer.

When the Connector Agent writes a Python handler for an operation, the handler is
delivered as a pull request rather than written into the running site, and
something has to decide WHICH repository receives it. That is
``connector_handler_app``, deliberately a setting rather than a constant: the
connector layer could be forked, vendored, or moved, and none of those should need
a code change to keep handler authoring working.

The field carries a default, which covers fresh installs. It does not cover this
one: Processa Settings is a Single that already exists, and Frappe applies a
field default when a document is created, not when a field is added to a document
that is already there. Without this patch every existing site keeps an empty
value — and an empty value disables handler authoring, so the agent would report
"no repository configured" on a site where nothing is actually wrong.

Only fills a blank. A site that has deliberately named a different app keeps it.
"""

import frappe

DEFAULT_APP = "one_bpmn"


def execute():
	# NOT frappe.db.has_column: Processa Settings is a Single, so it has no table
	# of its own and has_column raises TableMissingError rather than returning
	# False. Under `bench migrate --skip-failing` that exception is swallowed and
	# the patch is still recorded as applied — it would never run again, and the
	# field would stay blank with nothing to say why. This mirrors the reasoning
	# in set_customization_owner_app, which hit exactly that.
	if not frappe.get_meta("Processa Settings").has_field("connector_handler_app"):
		frappe.log_error(
			title="set_connector_handler_app: field not installed",
			message=(
				"Processa Settings has no connector_handler_app field, so the connector "
				"handler app was not set. Re-run this patch after the field installs, or set "
				"it by hand, or the Connector Agent will refuse to author Python handlers "
				"with 'no repository configured'."
			),
		)
		return

	if (frappe.db.get_single_value("Processa Settings", "connector_handler_app") or "").strip():
		return  # already chosen — leave it alone

	frappe.db.set_single_value("Processa Settings", "connector_handler_app", DEFAULT_APP)
