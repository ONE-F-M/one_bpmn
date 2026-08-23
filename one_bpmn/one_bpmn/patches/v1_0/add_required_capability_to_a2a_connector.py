# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002056: the delegate operation gains a declared capability.

The manifest in seed_a2a_connector carries the field for a fresh install; this
adds it to sites where that patch has already run, because the importer does not
overwrite an operation a site may have adjusted.

Also corrects the deadline help text. It told map authors the deadline comes
from the agent being delegated TO, which stopped being true when the limit moved
onto the delegating agent — where it belongs, beside depth, hand-offs and
retries.
"""

import frappe

OPERATION = "a2a-delegate_to_local_agent"

FIELD = {
	"field_name": "required_capability",
	"field_label": "Capability this needs",
	"field_type": "String",
	"required": 0,
	"help_text": (
		"Optional. One skill tag the agent must carry, e.g. 'connector'. Checked against "
		"the agent's A2A skill tags before anything is handed over, so a shape pointed at "
		"an agent that does not do this kind of work is refused instead of delegated. "
		"Leave blank for no constraint."
	),
}

DEADLINE_HELP = (
	"Usually leave blank: the deadline comes from the DELEGATING agent's configuration. "
	"Set this only to override it for this step."
)


def execute():
	if not frappe.db.exists("BPMN Connector Operation", OPERATION):
		return

	operation = frappe.get_doc("BPMN Connector Operation", OPERATION)
	existing = {row.field_name for row in operation.get("fields") or []}

	if FIELD["field_name"] not in existing:
		# Before the deadline override, so the two settings that shape WHO does
		# the work sit together and the override stays last.
		operation.append("fields", FIELD)
		rows = operation.get("fields")
		rows.insert(len(rows) - 2, rows.pop())
		for index, row in enumerate(rows, start=1):
			row.idx = index

	for row in operation.get("fields") or []:
		if row.field_name == "timeout_minutes":
			row.help_text = DEADLINE_HELP

	operation.flags.ignore_permissions = True
	operation.save(ignore_permissions=True)
