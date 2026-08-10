"""
WI-001998: deprecate User Task Assignment Log.

Reassigning a User Task on a deployed map used to write a row here as well as
saving the map. The map's own version history already carries the change —
BPMN Process Model has track_changes on, so the save records a Version holding
the bpmn_xml before and after, and the reassignment IS that diff. The log was a
second copy of the same fact in a place that could drift from the document it
described and had to be maintained by hand.

Removing the folder stops new sites getting the doctype. Existing sites keep
both the DocType record and its table until something deletes them, which is
what this does.

THE ROWS GO WITH IT. That is the point of the story rather than a side effect:
the requirement is that no log exists outside the version history, and leaving
the table behind would satisfy the letter of it while leaving the audit split
across two places — worse, in a table nothing manages any more. Verified before
writing this that the history survives: every logged reassignment on the origin
site belonged to a model whose Version rows carry the matching bpmn_xml changes.

WHY THE TABLE IS DROPPED EXPLICITLY

``frappe.delete_doc("DocType", ...)`` does NOT drop ``tab<DocType>``. Its
delete_from_table only removes the row from tabDocType and the doctype's child
rows; there is no DROP TABLE anywhere in that path. Deleting the doctype alone
leaves every row sitting in the database, invisible and unmanaged — which is
the exact thing this story exists to remove. Caught by checking the table after
the first run of this patch rather than trusting the delete.

Idempotent, and each half is guarded separately so a site left in either
half-state by an earlier partial removal is finished off correctly.
"""

import frappe

DOCTYPE = "User Task Assignment Log"


def execute():
	rows = frappe.db.count(DOCTYPE) if frappe.db.table_exists(DOCTYPE) else 0

	if frappe.db.exists("DocType", DOCTYPE):
		# Clears the surrounding records — Custom Field, Property Setter,
		# DocType Link — that a bare DROP TABLE would strand.
		frappe.delete_doc("DocType", DOCTYPE, force=True, ignore_permissions=True)

	# Separately guarded: the delete above does not do this, and a site may
	# already have lost the DocType record while keeping the table.
	if frappe.db.table_exists(DOCTYPE):
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{DOCTYPE}`")

	frappe.db.commit()

	if rows or not frappe.db.table_exists(DOCTYPE):
		print(f"WI-001998: removed {DOCTYPE} and its {rows} row(s)")
