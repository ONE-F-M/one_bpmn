"""ProsAlly can read the message and signal links to related process maps: creates the tool script, adds the get_process_links shape to its Tools sub-process and adds the link rules to the prompt."""

import re

import frappe

from one_bpmn.one_bpmn.patches.v1_0.add_assistant_agent_creation_tool import _XML_TOOL_ANCHOR, _di_xml, _shape_element

AGENT_ID = "prosally_agent"
ADHOC_ID = "prosally_tools"
TOOL_SCRIPT = "ProsAlly - Tool Process Links"
MARKER = "CROSS-PROCESS LINKS"

SCRIPT = """\
# ProsAlly tool: get_process_links. Reads the map open in this turn.
from one_bpmn.agents.process_links import process_links_for_turn

result["output"] = process_links_for_turn(context_docname)
"""

SHAPE = {
	"id": "get_process_links",
	"name": "get_process_links",
	"script": TOOL_SCRIPT,
	"documentation": (
		"Reads the message and signal links between the map open in this turn and the other process maps the "
		"designer can read, and lists the gaps: a catch with no throw, a throw with no catch, names that differ, "
		"a signal that cannot cross to another map, a call activity with no target. Read only. Call it once "
		"after search_dms_documents when the next tool is generate_process or modify_process. It takes no "
		"arguments. The stage tool reads what it finds."
	),
	"params": {"properties": {}, "required": []},
	# Free slot in the Tools sub-process, after search_dms_documents.
	"bounds": (1440, 460),
}

LINKS_PROMPT = """

CROSS-PROCESS LINKS:
- When classify_intent's `next` is generate_process or modify_process, call `get_process_links` once after `search_dms_documents` and before that tool. For those turns this overrides the call count above: classify_intent, search_dms_documents, get_process_links, the stage tool, finalize are five calls. Every other turn is unchanged.
- The stage tool reads what it found. Never call it again, and never put its output in another tool's arguments.
- When it returns an error or no gaps, go straight to the stage tool.
- You only ever change the map open in this turn. Gaps in other maps are explained to the designer, never edited."""


def execute():
	_upsert_tool_script()
	_update_process_model()
	append_prompt()


def _upsert_tool_script():
	if frappe.db.exists("Server Script", TOOL_SCRIPT):
		frappe.db.set_value("Server Script", TOOL_SCRIPT, "script", SCRIPT)
		return
	frappe.get_doc(
		{"doctype": "Server Script", "name": TOOL_SCRIPT, "script_type": "API", "allow_guest": 0, "disabled": 0, "script": SCRIPT}
	).insert(ignore_permissions=True)


def splice_shape(xml: str) -> str | None:
	"""The map with the shape inside the Tools sub-process and on the canvas; None when the sub-process is missing."""
	tools = re.search(rf'<bpmn:adHocSubProcess id="{ADHOC_ID}".*?</bpmn:adHocSubProcess>', xml, re.S)
	if not tools or _XML_TOOL_ANCHOR not in tools.group(0):
		return None
	if f'id="{SHAPE["id"]}"' not in xml:
		patched = tools.group(0).replace(_XML_TOOL_ANCHOR, _shape_element(SHAPE) + "\n      " + _XML_TOOL_ANCHOR, 1)
		xml = xml[: tools.start()] + patched + xml[tools.end() :]
	if f'bpmnElement="{SHAPE["id"]}"' not in xml:
		plane_end = xml.rfind("</bpmndi:BPMNPlane>")
		if plane_end == -1:
			return None
		xml = xml[:plane_end] + _di_xml(SHAPE["id"], *SHAPE["bounds"]) + "\n      " + xml[plane_end:]
	return xml


def _update_process_model():
	model = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "process_model")
	if not model:
		return

	xml = frappe.db.get_value("BPMN Process Model", model, "bpmn_xml") or ""
	patched = splice_shape(xml)
	if patched is None:
		frappe.log_error(
			title="ProsAlly process links tool: map anchors not found",
			message=f"'{model}' has no '{ADHOC_ID}' sub-process to add the shape to; add get_process_links by hand.",
		)
		return
	if patched == xml:
		return

	frappe.db.set_value("BPMN Process Model", model, "bpmn_xml", patched)

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(model)
	except frappe.ValidationError:
		frappe.log_error(
			title="ProsAlly process links tool: recompile refused",
			message=f"'{model}' has the shape but was not recompiled, so the tool is not live yet. Recompile it once the agent is Live.\n\n{frappe.get_traceback()}",
		)


def append_prompt():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if MARKER in prompt:
		return

	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.rstrip() + LINKS_PROMPT)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
