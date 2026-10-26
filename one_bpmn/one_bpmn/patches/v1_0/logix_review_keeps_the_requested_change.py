"""Logix's review step ignores a reviewer revision that puts the original script back.

The reviewer sees the draft but not what the person asked for, so its revised_script can undo the
requested change: a draft that switched IT to Operations came back as the untouched original, and
finalize published it with no diff. Idempotent by its marker.
"""

import frappe

SCRIPT = "Logix – Tool Review Script"
OLD = '        if (not _review.get("approved")) and _review.get("revised_script"):\n'
NEW = (
	"        # A revision equal to the original script undoes the change the person asked for.\n"
	'        _reverts = (_review.get("revised_script") or "").strip() == '
	'(turn.get("original_script_content") or "").strip()\n'
	'        if (not _review.get("approved")) and _review.get("revised_script") and not _reverts:\n'
)


def execute():
	code = frappe.db.get_value("Server Script", SCRIPT, "script")
	if not code or "_reverts" in code or code.count(OLD) != 1:
		return
	frappe.db.set_value("Server Script", SCRIPT, "script", code.replace(OLD, NEW), update_modified=False)
