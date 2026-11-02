"""LuCrusher can search the DMS: creates the tool script, adds the search_dms_documents shape to its tools sub-process and adds the DMS rules to the prompt."""

import re

import frappe

from one_bpmn.one_bpmn.patches.v1_0.add_assistant_agent_creation_tool import _di_xml
from one_bpmn.one_bpmn.patches.v1_0.add_assistant_eval_authoring_tools import _ensure_script, _shape_xml

AGENT_ID = "lucrusher_agent"
MODEL_NAME = "LuCrusher – Migration Agent"
ADHOC_ID = "lucrusher_tools"
SCRIPT_NAME = "LuCrusher - Tool DMS Search"
API_METHOD = "lucrusher_tool_search_dms_documents"
MARKER = "COMPANY DOCUMENTS (DMS)"
XML_TOOL_ANCHOR = "<bpmn:completionCondition"

SCRIPT = """\
# LuCrusher tool: search_dms_documents. The shape's arguments arrive in task_data.
from one_bpmn.agents.dms_search import search_dms_documents

result["output"] = search_dms_documents(task_data.get("query"), task_data.get("document_type"), instance=instance)
"""

SHAPE = {
	"id": "search_dms_documents",
	"name": "search_dms_documents",
	"script": SCRIPT_NAME,
	"documentation": (
		"Searches the controlled documents in the DMS (Policy, SOP, Manual, Guideline, Knowledge Base) for the "
		"rules that apply to the process being migrated. Read only. Returns the best matching excerpts with the "
		"document code, title and type."
	),
	"params": {
		"properties": {
			"query": {
				"type": "string",
				"description": "The process name and what you need to know, in natural language.",
			},
			"document_type": {
				"type": ["string", "null"],
				"description": "Optional filter: Policy, SOP, Manual, Guideline or Knowledge Base.",
			},
		},
		"required": ["query"],
	},
	"bounds": (1020, 460),
}

DMS_PROMPT = """

COMPANY DOCUMENTS (DMS):
- Before you draft or revise a topology, migration tasks or ProsAlly prompts, and when the user asks about a company policy, procedure, manual or guideline, call `search_dms_documents` with the process name and what you need as the query.
- Base what you take from the DMS only on the returned excerpts. When nothing is returned, say the DMS has nothing on the topic and do not fill the gap from general knowledge.
- Name the document you relied on by its code and title, and say what type it is.
- Document types: a Policy is mandatory and sets the rules; an SOP is the required step-by-step procedure; a Manual is reference material on how a system or tool works; a Guideline is recommended practice; a Knowledge Base article is informational.
- When documents of different types disagree, the type earlier in this order governs, and you must say that you are applying it: Policy, SOP, Manual, Guideline, Knowledge Base.
- Pass `document_type` when the user asks for one type.
- Do not paste raw tool output or document links into the answer."""


def execute():
	_ensure_script(SCRIPT_NAME, API_METHOD, SCRIPT)
	_update_process_model()
	append_prompt()


def splice_shape(xml: str) -> str | None:
	"""The map with the shape inside the tools sub-process and on the canvas; None when the sub-process is missing."""
	tools = re.search(rf'<bpmn:adHocSubProcess id="{ADHOC_ID}".*?</bpmn:adHocSubProcess>', xml, re.S)
	if not tools or XML_TOOL_ANCHOR not in tools.group(0):
		return None
	if f'id="{SHAPE["id"]}"' not in xml:
		patched = tools.group(0).replace(XML_TOOL_ANCHOR, _shape_xml(SHAPE) + XML_TOOL_ANCHOR, 1)
		xml = xml[: tools.start()] + patched + xml[tools.end() :]
	if f'bpmnElement="{SHAPE["id"]}"' not in xml:
		plane_end = xml.rfind("</bpmndi:BPMNPlane>")
		if plane_end == -1:
			return None
		xml = xml[:plane_end] + _di_xml(SHAPE["id"], *SHAPE["bounds"]) + "\n      " + xml[plane_end:]
	return xml


def _update_process_model():
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	patched = splice_shape(xml)
	if patched is None:
		frappe.log_error(
			title="LuCrusher DMS tool: map anchors not found",
			message=f"'{MODEL_NAME}' has no '{ADHOC_ID}' sub-process to add the shape to; add search_dms_documents by hand.",
		)
		return
	if patched == xml:
		return

	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", patched)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(MODEL_NAME)


def append_prompt():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if MARKER in prompt:
		return

	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.rstrip() + DMS_PROMPT)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
