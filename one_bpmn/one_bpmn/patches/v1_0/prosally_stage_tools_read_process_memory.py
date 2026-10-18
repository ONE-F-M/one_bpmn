"""ProsAlly's classify, generate and modify prompts carry the memory of the process being drawn.

Build Context recalls the memory of the Process the diagram is named after, Save Response queues
a write after a drawn or changed diagram, and the orchestrator task stops using memory itself.
Edits the live Server Scripts by anchor; a script that already has its marker is left alone.
"""

import frappe

DASH = "\u2013"
AGENT_ID = "prosally_agent"

# Server Script -> (marker, anchor, replacement). Each anchor must appear exactly once.
EDITS = {
	f"ProsAlly {DASH} Build Context": (
		"recall_process_memory",
		"# The AI Agent Task does tool-calling internally",
		"from one_bpmn.agents.prosally_helpers import recall_process_memory\n"
		"from one_bpmn.agents.turn_state import update_turn\n"
		'update_turn(conversation_id, **recall_process_memory(task_data.get("diagram_name", "")))\n\n'
		"# The AI Agent Task does tool-calling internally",
	),
	f"ProsAlly {DASH} Tool Classify Intent": (
		'stage_system_prompt(_cfg, "intent_classifier"',
		'data = extract_json(complete_sub_prompt(_cfg, "intent_classifier", prompt))',
		"from one_bpmn.agents.prosally_helpers import stage_system_prompt\n"
		'    _system = stage_system_prompt(_cfg, "intent_classifier", "", turn)\n'
		'    data = extract_json(complete_sub_prompt(_cfg, "intent_classifier", prompt, system=_system))',
	),
	f"ProsAlly {DASH} Tool Generate Process": (
		'"generate_skills", turn)',
		'_system = stage_system_prompt(_cfg, "process_generator", "generate_skills")',
		'_system = stage_system_prompt(_cfg, "process_generator", "generate_skills", turn)',
	),
	f"ProsAlly {DASH} Tool Modify Process": (
		'"modify_skills", turn)',
		'_system = stage_system_prompt(_cfg, "modifier", "modify_skills")',
		'_system = stage_system_prompt(_cfg, "modifier", "modify_skills", turn)',
	),
	f"ProsAlly {DASH} Save Response": (
		"queue_process_memory",
		'result["response_saved"] = True',
		"from one_bpmn.agents.prosally_helpers import queue_process_memory\n"
		"queue_process_memory(_turn, agent_result)\n"
		'result["response_saved"] = True',
	),
}


def apply_edit(code, anchor, replacement):
	"""The script with the edit applied, or None when the anchor is not found exactly once."""
	if code.count(anchor) != 1:
		return None
	return code.replace(anchor, replacement)


def execute():
	for name, (marker, anchor, replacement) in EDITS.items():
		if not frappe.db.exists("Server Script", name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		if marker in code:
			continue
		patched = apply_edit(code, anchor, replacement)
		if patched is None:
			frappe.log_error(
				title="ProsAlly process memory: anchor not found",
				message=f"{name} no longer matches the text this patch edits; add the memory lines by hand.",
			)
		else:
			frappe.db.set_value("Server Script", name, "script", patched, update_modified=False)

	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if config:
		frappe.db.set_value(
			"AI Agent Configuration", config, {"long_term_memory": "Disabled", "memory_write_mode": "off"}
		)
