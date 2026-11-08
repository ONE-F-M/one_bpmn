"""ProsAlly can search the DMS: creates the tool script, adds the search_dms_documents shape to its Tools sub-process and adds the DMS rules to the prompt."""

import re

import frappe

from one_bpmn.one_bpmn.patches.v1_0.add_assistant_agent_creation_tool import _XML_TOOL_ANCHOR, _di_xml, _shape_element

AGENT_ID = "prosally_agent"
ADHOC_ID = "prosally_tools"
TOOL_SCRIPT = "ProsAlly - Tool DMS Search"
MARKER = "COMPANY DOCUMENTS (DMS)"

SCRIPT = """\
# ProsAlly tool: search_dms_documents. The shape's arguments arrive in task_data.
from one_bpmn.agents.prosally_helpers import search_dms_for_turn

result["output"] = search_dms_for_turn(context_docname, task_data.get("query"), task_data.get("document_type"), instance=instance)
"""

SHAPE = {
	"id": "search_dms_documents",
	"name": "search_dms_documents",
	"script": TOOL_SCRIPT,
	"documentation": (
		"Searches the controlled documents in the DMS (Policy, SOP, Manual, Guideline, Knowledge Base) for the "
		"rules that apply to the process being drawn or changed. Read only. Call it once after classify_intent "
		"when the next tool is generate_process or modify_process, with the process name and what the designer "
		"asked for as the query. The stage tool reads what it finds."
	),
	"params": {
		"properties": {
			"query": {
				"type": "string",
				"description": "The process name and what the designer asked for, in natural language.",
			},
			"document_type": {
				"type": ["string", "null"],
				"description": "Optional filter: Policy, SOP, Manual, Guideline or Knowledge Base.",
			},
		},
		"required": ["query"],
	},
	# Free slot in the Tools sub-process, after generate_process, modify_process and finalize.
	"bounds": (1310, 460),
}

DMS_PROMPT = """

COMPANY DOCUMENTS (DMS):
- When classify_intent's `next` is generate_process or modify_process, call `search_dms_documents` once before that tool, with the process name and what the designer asked for as the query. For those turns this overrides the three-call count above: classify_intent, search_dms_documents, the stage tool, finalize are four calls. Every other turn stays at three.
- The stage tool reads what the search found. Never search again, and never put document text in another tool's arguments.
- When the search returns nothing or fails, go straight to the stage tool.
- Document types: a Policy is mandatory and sets the rules; an SOP is the required step-by-step procedure; a Manual is reference material on how a system or tool works; a Guideline is recommended practice; a Knowledge Base article is informational. When they disagree, the type earlier in this order governs: Policy, SOP, Manual, Guideline, Knowledge Base."""


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
			title="ProsAlly DMS tool: map anchors not found",
			message=f"'{model}' has no '{ADHOC_ID}' sub-process to add the shape to; add search_dms_documents by hand.",
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
			title="ProsAlly DMS tool: recompile refused",
			message=f"'{model}' has the shape but was not recompiled, so the tool is not live yet. Recompile it once the agent is Live.\n\n{frappe.get_traceback()}",
		)


def append_prompt():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if MARKER in prompt:
		return

	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.rstrip() + DMS_PROMPT)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
