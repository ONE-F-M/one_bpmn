"""ProsAlly names the sub-process a modify changed, so the diagram preview opens that sub-process.

Edits the Tool Modify Process script in place. One already carrying the change is skipped, and one whose
anchor is not found exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

MODIFY_SCOPE_ID = (
	'            "response": _reply,\n',
	'            "response": _reply,\n            "scope_id": scope["id"] if scope else "",\n',
)
MARKER = '"scope_id": scope["id"]'


def execute():
	name = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "name")
	if name:
		apply_edits("Server Script", name, "script", (MODIFY_SCOPE_ID,), MARKER)
