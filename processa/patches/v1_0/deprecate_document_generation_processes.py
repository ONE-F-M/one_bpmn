# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Retire the per-document-type generation Process masters.

The four BPMN maps that generated SOPs, Policies and Manuals were replaced by
one map — "Document Request" — which takes ``document_type`` as a parameter.
The maps themselves are gone. Their **Process masters** were left behind, so
the process taxonomy still advertises three processes that nothing implements:

    Manual Generation from Guidelines
    Policy Generation from Guideline      (singular — the deployed one)
    SOP Generation from Guidelines

A Process master with no map is not harmless. It shows up in the process
hierarchy, in pickers, and in Pathfinder as though it were a real, runnable
process — so a Business Analyst can author against something that can never
execute. That is exactly what happened here: two Process Implementation rows
were opened against "SOP Generation from Guidelines" after its map was
deleted.

WHY DELETE RATHER THAN FLAG
---------------------------
Process has no ``is_active`` / ``status`` field to switch off, so there is no
"deprecated" state to move these into. The choices are delete, or leave them
misleading. They are deleted.

WHAT IS NOT DELETED
-------------------
The 23 historical BPMN Process Instances from the old maps. They already point
at deleted models and are kept deliberately as an audit trail — removing the
Process masters does not touch them.
"""

import frappe

# The three masters left orphaned when their maps were unified. Named exactly —
# note "Policy Generation from Guideline" is singular; the plural variant was an
# abandoned clone that never had its own master.
DEPRECATED_PROCESSES = (
	"Manual Generation from Guidelines",
	"Policy Generation from Guideline",
	"SOP Generation from Guidelines",
)

# The map that replaced them. Its presence is the precondition for this patch:
# deleting the old masters before the replacement exists would leave the
# taxonomy with no document-generation process at all.
REPLACEMENT_PROCESS = "Document Request"


def execute():
	if not frappe.db.exists("Process", REPLACEMENT_PROCESS):
		frappe.log_error(
			title="Document generation deprecation skipped",
			message=(
				f"Process master {REPLACEMENT_PROCESS!r} does not exist, so the "
				"per-type masters were left in place. Import the unified "
				"'Document Request' process map first, then re-run this patch."
			),
		)
		return

	for process in DEPRECATED_PROCESSES:
		if not frappe.db.exists("Process", process):
			continue  # already retired — the patch is idempotent
		_retire(process)


def _retire(process: str) -> None:
	"""Delete one orphaned Process master and the rows that point at it."""
	# A Process Implementation is authored against a process; with the process
	# gone it is unreachable. Delete the ones belonging to this master first,
	# otherwise the Link leaves the master undeletable.
	implementations = frappe.get_all(
		"Process Implementation",
		filters={"process_name": process},
		fields=["name", "docstatus"],
	)
	for implementation in implementations:
		# force=True skips the *link* check, not the *submitted* check —
		# check_permission_and_not_submitted runs first and refuses outright.
		# Cancel in the database rather than calling .cancel(), which would run
		# the workflow's own transitions on a record being retired anyway.
		if implementation.docstatus == 1:
			frappe.db.set_value(
				"Process Implementation",
				implementation.name,
				"docstatus",
				2,
				update_modified=False,
			)
		frappe.delete_doc(
			"Process Implementation", implementation.name, force=True, ignore_permissions=True
		)

	# force=True is what skips check_if_doc_is_linked — there is no ignore_links
	# kwarg. Needed because other records may still Link to a master that, by
	# definition, no longer has anything behind it.
	frappe.delete_doc("Process", process, force=True, ignore_permissions=True)

	frappe.db.commit()
	print(
		f"Retired Process master {process!r}"
		+ (f" and {len(implementations)} Process Implementation row(s)" if implementations else "")
	)
