"""ProsAlly counts rebuilt flow references as a change only when the person asked for a lint fix.

Edits the Modify Process script in place. One already carrying the change is skipped, and one whose anchor is not
found exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

REFS_ONLY_FOR_LINT_FIX = (
	r'''_refs = "" if ("\n- " in _changes or _links) else describe_flow_references(current_xml, merged_xml)''',
	r'''_refs = "" if ("\n- " in _changes or _links or not lint_fix) else describe_flow_references(current_xml, merged_xml)''',
)
MARKER = "or not lint_fix) else describe_flow_references"


def execute():
	name = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "name")
	if name:
		apply_edits("Server Script", name, "script", (REFS_ONLY_FOR_LINT_FIX,), MARKER)
