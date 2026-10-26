"""ProsAlly says when the step asked for is already there, and shows no Apply card for a modify that changed nothing.

Edits the Classify Intent and Modify Process scripts in place. One already carrying the change is skipped, and one
whose anchors are not each found exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

CLASSIFY_ALREADY = (
	'describe it as updating that sub-process.")\n',
	r'''describe it as updating that sub-process.")
        from one_bpmn.agents.prosally_helpers import similar_steps
        _same = similar_steps(scope["xml"], _scope_texts, scope["name"])
        if _same:
            _parts.append("That sub-process already has " + ", ".join('"' + s + '"' for s in _same) + ", which looks like this request. Say so in the summary and ask whether to add another one anyway.")
''',
)
MODIFY_NOTHING_CHANGED = (
	'        else:\n            _reply = _changes.strip() + note\n        output = {\n            "intent": "BPMN_MODIFIED",\n'
	'            "action_intent": "MODIFY_EXISTING",\n            "bpmn_xml": merged_xml,\n',
	r'''        else:
            from one_bpmn.agents.prosally_helpers import no_change_reply, similar_steps
            _reply = no_change_reply(
                ("the sub-process \"" + scope["name"] + "\"") if scope else "the process",
                similar_steps(scope["xml"] if scope else current_xml, _scope_texts, scope["name"] if scope else ""),
            )
        output = {
            "intent": "BPMN_MODIFIED" if "\n- " in _changes else "CLARIFY",
            "action_intent": "MODIFY_EXISTING",
''',
)
MODIFY_ATTACH_XML = (
	'        update_turn(context_docname, output=output, done=True)\n        result["modified"] = True\n',
	'        if "\\n- " in _changes:\n            output["bpmn_xml"] = merged_xml\n'
	'        update_turn(context_docname, output=output, done=True)\n        result["modified"] = "\\n- " in _changes\n',
)

# Server Script name pattern -> (edits, marker of an applied change).
SCRIPTS = {
	"ProsAlly%Tool Classify Intent": ((CLASSIFY_ALREADY,), "similar_steps("),
	"ProsAlly%Tool Modify Process": ((MODIFY_NOTHING_CHANGED, MODIFY_ATTACH_XML), "no_change_reply("),
}


def execute():
	for pattern, (edits, marker) in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			apply_edits("Server Script", name, "script", edits, marker)
