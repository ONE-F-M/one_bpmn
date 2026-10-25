"""ProsAlly fixes the lint findings the editor shows, in the process or the sub-process they sit in.

Edits the Build Context, Classify Intent and Modify Process scripts in place. One already carrying the change is
skipped, and one whose anchors are not each found exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

CONTEXT_KEYS = (
	"'current_xml', 'scope_id']:",
	"'current_xml', 'scope_id', 'lint_issues']:",
)
CONTEXT_TURN = (
	'    "scope_id": task_data.get("scope_id", "") or "",\n})',
	'    "scope_id": task_data.get("scope_id", "") or "",\n    "lint_issues": task_data.get("lint_issues") or [],\n})',
)
CLASSIFY_LINT = (
	"    if scope and not convert:\n",
	r'''    from one_bpmn.agents.prosally_helpers import lint_findings, lint_fix_requested, lint_prompt
    lint_fix = None
    lint_none = False
    if lint_fix_requested(_scope_texts):
        lint_fix = lint_findings(current_xml, turn.get("lint_issues") or [], turn.get("scope_id", ""))
        lint_none = not (lint_fix and lint_fix["fix"])
        if lint_fix:
            scope = lint_fix["scope"]
            convert = None
        if not lint_none:
            _parts.append("The person asks to fix the lint findings the editor shows. Classify it as MODIFY_EXISTING and describe it as fixing exactly these, never as drawing or redrawing the process:\n" + lint_prompt(lint_fix))
    if scope and not convert:
''',
)
CLASSIFY_GUARD = (
	"    # An overwrite that would discard configured shapes still asks, so its warning is seen.\n",
	r'''    if lint_fix and not lint_none and intent in _GENERATE_INTENTS:
        intent = "MODIFY_EXISTING"
    if lint_none and intent in _ACTION_INTENTS:
        intent = "AMBIGUOUS"
        reason = "There are no lint findings that can be fixed by editing the diagram."
    # An overwrite that would discard configured shapes still asks, so its warning is seen.
''',
)
CLASSIFY_REPLY = (
	'        result["next"] = "clarify"\n        if wants_call:\n',
	r'''        result["next"] = "clarify"
        if lint_none:
            from one_bpmn.agents.prosally_helpers import no_lint_fix_reply
            update_turn(context_docname, output={"intent": "CLARIFY", "action_intent": None, "response": no_lint_fix_reply(lint_fix), "options": []}, done=True)
            result["next"] = "finalize"
        elif wants_call:
''',
)
MODIFY_LINT = (
	"if convert:\n    scope = None\n",
	r'''if convert:
    scope = None
from one_bpmn.agents.prosally_helpers import lint_findings, lint_fix_requested, lint_leftovers, lint_prompt
lint_fix = None
if lint_fix_requested(_scope_texts):
    lint_fix = lint_findings(current_xml, turn.get("lint_issues") or [], turn.get("scope_id", ""))
    if lint_fix:
        scope = lint_fix["scope"]
        convert = None
''',
)
MODIFY_PROMPT = (
	"if ghost:\n    initial_prompt = initial_prompt + ",
	r'''if lint_fix and lint_fix["fix"]:
    initial_prompt = initial_prompt + "\n\nThe person asked to fix lint findings. Fix exactly these and change nothing else. Keep every existing id. Connect an element that is not connected, add a missing start or end event, name an unnamed element, remove a duplicate flow, and give a gateway path the condition or default it needs. Do not remove a step unless a finding says it is superfluous.\n" + lint_prompt(lint_fix)
if ghost:
    initial_prompt = initial_prompt + ''',
)
MODIFY_LINKS = (
	"        _changes = describe_changes(current_xml, merged_xml)\n",
	r'''        _changes = describe_changes(current_xml, merged_xml)
        from one_bpmn.agents.prosally_helpers import describe_links
        _links = "" if "\n- " in _changes else describe_links(current_xml, merged_xml)
        _changed = "\n- " in _changes or bool(_links)
''',
)
MODIFY_LINKS_REPLY = (
	"        else:\n            from one_bpmn.agents.prosally_helpers import no_change_reply, similar_steps\n",
	r'''        elif _links:
            _reply = ("I've updated the " + _where + "." + note + " All existing configurations have been preserved. Review the changes on the canvas.") + _links
        else:
            from one_bpmn.agents.prosally_helpers import no_change_reply, similar_steps
''',
)
MODIFY_REPLY = (
	'        output = {\n            "intent": "BPMN_MODIFIED" if "\\n- " in _changes else "CLARIFY",\n',
	'        if lint_fix:\n            _reply = _reply + lint_leftovers(lint_fix)\n'
	'        output = {\n            "intent": "BPMN_MODIFIED" if _changed else "CLARIFY",\n',
)
MODIFY_ATTACH = (
	'        if "\\n- " in _changes:\n            output["bpmn_xml"] = merged_xml\n'
	'        update_turn(context_docname, output=output, done=True)\n        result["modified"] = "\\n- " in _changes\n',
	'        if _changed:\n            output["bpmn_xml"] = merged_xml\n'
	"        update_turn(context_docname, output=output, done=True)\n        result[\"modified\"] = _changed\n",
)

# Server Script name pattern -> (edits, marker of an applied change).
SCRIPTS = {
	"ProsAlly%Build Context": ((CONTEXT_KEYS, CONTEXT_TURN), "lint_issues"),
	"ProsAlly%Tool Classify Intent": ((CLASSIFY_LINT, CLASSIFY_GUARD, CLASSIFY_REPLY), "lint_findings("),
	"ProsAlly%Tool Modify Process": (
		(MODIFY_LINT, MODIFY_PROMPT, MODIFY_LINKS, MODIFY_LINKS_REPLY, MODIFY_REPLY, MODIFY_ATTACH),
		"lint_findings(",
	),
}


def execute():
	for pattern, (edits, marker) in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			apply_edits("Server Script", name, "script", edits, marker)
