"""Docu's reply says when a design names a standard child table whose columns it cannot change.

The Review script keeps the validator's warnings on the turn and the Finalize script appends them to the reply.
Idempotent: a script already carrying the change, or missing the anchor line, is left as it is.
"""

import frappe

REVIEW = "Docu – Tool Review Schema"
FINALIZE = "Docu – Tool Finalize"

REVIEW_OLD = "            schema_safe=True, violations=[],\n        )"
REVIEW_NEW = '            schema_safe=True, violations=[], warnings=validation["warnings"],\n        )'

FINALIZE_OLD = '        ir = turn.get("final_ir")\n        # Question passthrough'
FINALIZE_NEW = '        final_text = "\\n\\n".join([final_text] + list(turn.get("warnings") or []))\n' + FINALIZE_OLD


def execute():
	for name, old, new in ((REVIEW, REVIEW_OLD, REVIEW_NEW), (FINALIZE, FINALIZE_OLD, FINALIZE_NEW)):
		if not frappe.db.exists("Server Script", name):
			continue
		doc = frappe.get_doc("Server Script", name)
		if old in doc.script and new not in doc.script:
			doc.script = doc.script.replace(old, new, 1)
			doc.save(ignore_permissions=True)
