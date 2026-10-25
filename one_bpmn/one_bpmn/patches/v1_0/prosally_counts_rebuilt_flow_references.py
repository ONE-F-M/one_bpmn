"""ProsAlly returns a lint fix that only rebuilds flow references, and says how many findings it could not fix.

Edits the Modify Process script in place. One already carrying the change is skipped, and one whose anchors are not
each found exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

IMPORT = (
	"from one_bpmn.agents.prosally_helpers import lint_findings, lint_fix_requested, lint_leftovers, lint_prompt\n",
	"from one_bpmn.agents.prosally_helpers import lint_findings, lint_fix_requested, lint_leftovers, lint_prompt, "
	"lint_unfixed_reply\n",
)
CHANGED = (
	'        _changed = "\\n- " in _changes or bool(_links)\n',
	r'''        from one_bpmn.agents.prosally_helpers import describe_flow_references
        _refs = "" if ("\n- " in _changes or _links) else describe_flow_references(current_xml, merged_xml)
        _changed = "\n- " in _changes or bool(_links) or bool(_refs)
''',
)
REPLY = (
	"        else:\n            from one_bpmn.agents.prosally_helpers import no_change_reply, similar_steps\n",
	r'''        elif _refs:
            _reply = ("I've updated the " + _where + "." + note + " All existing configurations have been preserved. Review the changes on the canvas.") + _refs
        else:
            from one_bpmn.agents.prosally_helpers import no_change_reply, similar_steps
''',
)
UNFIXED = (
	"        if lint_fix:\n            _reply = _reply + lint_leftovers(lint_fix)\n",
	r'''        if lint_fix:
            if not _changed and lint_fix["fix"]:
                _reply = lint_unfixed_reply("the " + _where, lint_fix)
            _reply = _reply + lint_leftovers(lint_fix)
''',
)
MARKER = "describe_flow_references("
EDITS = (IMPORT, CHANGED, REPLY, UNFIXED)


def execute():
	name = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "name")
	if name:
		apply_edits("Server Script", name, "script", EDITS, MARKER)
