"""The delegate operation gains work_item and pull_request.

seed_a2a_connector carries them for a fresh install; this adds them to sites
where that patch has already run, because the importer does not overwrite an
operation a site may have adjusted. Same shape as add_required_capability.
"""

import frappe

OPERATION = "a2a-delegate_to_local_agent"
FIELDS = [
	{
		"field_name": "work_item",
		"field_label": "Work Item",
		"field_type": "String",
		"required": 0,
		"help_text": (
			"Optional. The Work Item this delegation is about, normally {{ doc.name }}. "
			"The specialist gets it in its A2A Task and can read the record itself."
		),
	},
	{
		"field_name": "pull_request",
		"field_label": "Pull request",
		"field_type": "String",
		"required": 0,
		"help_text": "Optional. The pull request to fix or review, normally {{ doc.pr_link }}.",
	},
]


def execute():
	if not frappe.db.exists("BPMN Connector Operation", OPERATION):
		return
	operation = frappe.get_doc("BPMN Connector Operation", OPERATION)
	rows = operation.get("fields") or []
	existing = {row.field_name for row in rows}
	missing = [f for f in FIELDS if f["field_name"] not in existing]
	if not missing:
		return
	# The two override fields stay last; the new references sit with the work.
	overrides = [r for r in rows if r.field_name in ("required_capability", "timeout_minutes")]
	kept = [r for r in rows if r not in overrides]
	operation.set("fields", [])
	for row in kept:
		operation.append("fields", row.as_dict(no_default_fields=True))
	for field in missing:
		operation.append("fields", field)
	for row in overrides:
		operation.append("fields", row.as_dict(no_default_fields=True))
	operation.flags.ignore_permissions = True
	operation.save(ignore_permissions=True)
