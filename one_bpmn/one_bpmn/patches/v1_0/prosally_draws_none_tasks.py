"""ProsAlly keeps None tasks when it modifies a non-executable process and replaces every task with them on request.

Edits the Modify Process and Classify Intent Server Scripts and the intent_classifier sub-prompt by anchor. Text that
already carries its marker is skipped, and one whose anchors are not each found exactly once is logged and left alone.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits
from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID, edit_prompt

MODIFY_EDITS = (
	(
		"import complete_sub_prompt, convert_step_to_subprocess, ",
		"import complete_sub_prompt, convert_step_to_subprocess, keep_process_kind, ",
	),
	(
		"    auto_fixes.extend(auto_fix_ir(ir_dict))\n    _res = compile_ir(ir_dict)\n",
		"    auto_fixes.extend(auto_fix_ir(ir_dict))\n    keep_process_kind(ir_dict, current_xml)\n    _res = compile_ir(ir_dict)\n",
	),
)
MODIFY_MARKER = "keep_process_kind(ir_dict, current_xml)"

CLASSIFY_EDITS = (
	(
		"compare_output, relayout_output, ",
		"compare_output, none_tasks_output, relayout_output, ",
	),
	(
		'if confirmed == "RELAYOUT":\n',
		'if confirmed == "TASKS_TO_NONE":\n'
		'    _output = none_tasks_output(turn.get("current_xml", ""))\n'
		'    update_turn(context_docname, intent="TASKS_TO_NONE", confirmed=True, output=_output, done=True)\n'
		'    result["intent"] = "TASKS_TO_NONE"\n'
		'    result["modified"] = "bpmn_xml" in _output\n'
		'    result["next"] = "finalize"\n'
		'elif confirmed == "RELAYOUT":\n',
	),
	(
		'frozenset({"IRRELEVANT", "RELAYOUT", "COMPARE"})',
		'frozenset({"IRRELEVANT", "RELAYOUT", "TASKS_TO_NONE", "COMPARE"})',
	),
)
CLASSIFY_MARKER = "none_tasks_output("

PROMPT_EDITS = (
	(
		"and write the confirmation as laying the diagram out again with every step, arrow and setting kept.\n",
		"and write the confirmation as laying the diagram out again with every step, arrow and setting kept.\n"
		"- CRITICAL: When the person asks to replace all the existing tasks with None tasks (also called plain, "
		"generic or untyped tasks), classify as TASKS_TO_NONE, not MODIFY_EXISTING, and write the confirmation as "
		"making every task a None task with its name and arrows kept and its task settings removed. This applies "
		"to non-executable processes only.\n",
	),
	(
		"MODIFY_EXISTING, or RELAYOUT, also write the confirmation message",
		"MODIFY_EXISTING, RELAYOUT, or TASKS_TO_NONE, also write the confirmation message",
	),
	("MODIFY_EXISTING|RELAYOUT|COMPARE|", "MODIFY_EXISTING|RELAYOUT|TASKS_TO_NONE|COMPARE|"),
)
PROMPT_MARKER = "classify as TASKS_TO_NONE"

SCRIPTS = {
	"ProsAlly%Tool Modify Process": (MODIFY_EDITS, MODIFY_MARKER),
	"ProsAlly%Tool Classify Intent": (CLASSIFY_EDITS, CLASSIFY_MARKER),
}


def execute():
	for pattern, (edits, marker) in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			apply_edits("Server Script", name, "script", edits, marker)
	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if config:
		edit_prompt(config, "intent_classifier", PROMPT_EDITS, PROMPT_MARKER)
		frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
