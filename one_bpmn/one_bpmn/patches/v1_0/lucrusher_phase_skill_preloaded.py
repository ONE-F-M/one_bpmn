"""LuCrusher's system prompt tells the model its phase skill usually arrives already loaded.

Build Context loads the skill the next phase needs and unloads the others, so load_skill becomes
the fallback for a phase it did not predict. A prompt a person has since edited is left alone.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.move_lucrusher_turn_instructions_to_system import _AGENT_ID as AGENT_ID

OLD_LOAD = (
	"## Phases 4 to 6: load the phase skill first\n"
	"Before you draft or revise a topology, migration tasks or ProsAlly prompts, call load_skill with "
	"that phase's skill, then do the work in the same turn."
)
NEW_LOAD = (
	"## Phases 4 to 6: the phase skill\n"
	"Each of these phases has a skill with its rules. The platform loads the skill the next phase needs "
	'before your turn, so when it is already under "## Loaded Skills", do the work straight away. Call '
	"load_skill only when the skill for the phase you are drafting or revising is not loaded, then do the "
	"work in the same turn."
)
OLD_UNLOAD = " When you start a new phase, call unload_skill on the previous phase's skill."


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if OLD_LOAD not in prompt:
		return
	prompt = prompt.replace(OLD_LOAD, NEW_LOAD).replace(OLD_UNLOAD, "")
	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt)
