"""ProsAlly says which records, states and assignees it will set before drawing, and lists what it set after.

The go-ahead message names the planned settings and offers "draw only", the generator honours it and
uses only records the conversation named, and the generate and modify replies list the diagram's
settings. Edits each text in place once; one whose anchor moved is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

AGENT_ID = "prosally_agent"

CLASSIFIER_ANCHOR = "- List the main steps or decisions you understood from their description.\n"
CLASSIFIER_ADD = (
	"- If the request names a record the process works on, such as a Visa Request or an Incident Report, "
	"also list the settings you would put on the steps, in plain words: which record starts the process, "
	"which record each step works on, the status each change moves it to, and who each task goes to. "
	'Then tell them they can reply "draw only" to get the steps without these settings.\n'
	"- Only name a record the person mentioned. If you cannot tell which record they mean, or more than one "
	"could fit, name the ones you are unsure between and ask which they mean instead of choosing.\n"
	"- If the person asked for the drawing only, say you will draw the steps without any settings.\n"
)

GENERATOR_ANCHOR = "Use the key names exactly as written below."
GENERATOR_ADD = (
	"Only configure what the person agreed to. If the conversation shows they asked for the drawing only, "
	"or declined the settings in the confirmation, leave out every config object. Only use a DocType the "
	"person named or agreed to in the conversation; never pick one because its name looks close.\n\n"
)

SCRIPTS = {
	"ProsAlly%Tool Generate Process": (
		(
			"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, extract_json, ",
			"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, describe_task_config, extract_json, ",
		),
		(
			'" Review it on the canvas.",\n',
			'" Review it on the canvas." + describe_task_config(best_xml),\n',
		),
	),
	"ProsAlly%Tool Modify Process": (
		(
			"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, extract_json, ",
			"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, describe_task_config, extract_json, ",
		),
		(
			'"have been preserved. Review the changes on the canvas."\n            ),\n',
			'"have been preserved. Review the changes on the canvas."\n'
			"            ) + describe_task_config(merged_xml, current_xml),\n",
		),
	),
}


def execute():
	update_prompts()
	for pattern, replacements in SCRIPTS.items():
		update_script(pattern, replacements)


def update_prompts():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	config = frappe.get_doc("AI Agent Configuration", name)
	edits = {
		"intent_classifier": (CLASSIFIER_ANCHOR, CLASSIFIER_ANCHOR + CLASSIFIER_ADD),
		"process_generator": (GENERATOR_ANCHOR, GENERATOR_ADD + GENERATOR_ANCHOR),
	}
	changed = False
	for row in config.sub_prompts:
		if row.sub_agent_id not in edits:
			continue
		text = apply_edit(row.prompt_text, *edits[row.sub_agent_id])
		if text is None:
			frappe.log_error(
				title="prosally_says_what_it_sets: prompt anchor not found",
				message=f"The {row.sub_agent_id} prompt does not carry its anchor exactly once; it is left as it is.",
			)
		elif text != row.prompt_text:
			row.prompt_text = text
			changed = True
	if changed:
		config.save(ignore_permissions=True)


def update_script(pattern: str, replacements: tuple) -> None:
	name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
	if not name:
		return
	doc = frappe.get_doc("Server Script", name)
	script = doc.script
	for anchor, replacement in replacements:
		script = apply_edit(script, anchor, replacement)
		if script is None:
			frappe.log_error(
				title="prosally_says_what_it_sets: anchors not found",
				message=f"{name} does not carry each anchor exactly once; the script is left as it is.",
			)
			return
	if script != doc.script:
		doc.script = script
		doc.save(ignore_permissions=True)
