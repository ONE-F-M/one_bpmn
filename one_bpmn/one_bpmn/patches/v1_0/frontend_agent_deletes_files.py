"""write_file refuses empty content and the Frontend Agent gets a delete_file tool.

An agent with no way to remove a file emptied it with write_file instead, and an empty JSON file broke
bench migrate for every later sandbox run. Write File now refuses empty content and names delete_file,
which is a new Server Script and a new shape in the Frontend Agent's tools. The agent's prompt names it,
and the Baseline suite gains a case that removes a file. Idempotent.
"""

import json

import frappe
from one_bpmn.one_bpmn.patches.v1_0.frontend_agent_reads_in_windows import _edit_named

from one_bpmn.one_bpmn.patches.v1_0.seed_frontend_agent_eval_suite import (
	AGENT,
	MAP,
	SHAPE,
	_fixture_task,
	_suite,
)

WRITE_FILE = "Sandbox Tool: Write File"
DELETE_FILE = "Sandbox Tool: Delete File"

WRITE_CONTENT_CHECK = """elif content is None:
    result["error"] = "content is required -- the file's full new content, not a diff."
"""
WRITE_EMPTY_CHECK = (
	WRITE_CONTENT_CHECK
	+ """elif not str(content).strip() and path.rsplit("/", 1)[-1] not in ("__init__.py", ".gitkeep"):
    result["error"] = (
        "content is empty. write_file never empties a file: to remove " + path + ", call delete_file."
    )
"""
)

DELETE_FILE_SCRIPT = """# Sandbox tool: delete_file. Shared verbatim by every sandbox agent, so nothing here may be agent-specific.
# Removes one file from the target app's checked-out working tree; the sandbox commits and pushes the deletion.
from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import sandbox_dispatch

target_app = (task_data.get("target_app") or "").strip()
git_branch = (task_data.get("git_branch") or "").strip()
work_item_description = (task_data.get("work_item_description") or "").strip()
path = (task_data.get("path") or "").strip()

if not (target_app and git_branch and work_item_description):
    result["error"] = "target_app, git_branch, and work_item_description are all required -- pass the exact same values on every call for one work order."
elif not path:
    result["error"] = "path is required, e.g. spiff/src/components/Old.vue"
else:
    _dispatch = sandbox_dispatch(
        "delete_file", target_app, git_branch, work_item_description, {"path": path}, context_docname, bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""

TOOL_PARAMS = {
	"properties": {
		"target_app": {
			"type": "string",
			"description": "The same target_app as every other sandbox call for this work order.",
		},
		"git_branch": {
			"type": "string",
			"description": "The same git_branch as every other sandbox call for this work order.",
		},
		"work_item_description": {
			"type": "string",
			"description": "The work order in plain words, byte-for-byte identical on every call.",
		},
		"path": {"type": "string", "description": "Repo-relative path of the file to remove."},
	},
	"required": ["target_app", "git_branch", "work_item_description", "path"],
}
DELETE_SHAPE = (
	'<bpmn:scriptTask id="delete_file" name="Delete a file" spiffworkflow:serverScript="Sandbox Tool: Delete File"'
	' spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Sandbox Tool: Delete File"'
	' spiffworkflow:aiToolParams="{params}">\n'
	"        <bpmn:documentation>Remove a file from the work order's branch and commit the deletion. "
	"Use this to get rid of a file; never write empty content to it.</bpmn:documentation>\n"
	"        <bpmn:script>Sandbox Tool: Delete File</bpmn:script>\n"
	"      </bpmn:scriptTask>\n"
	"    "
)
DELETE_SHAPE_DI = (
	'<bpmndi:BPMNShape id="delete_file_di" bpmnElement="delete_file">\n'
	'        <dc:Bounds x="825" y="540" width="120" height="70" />\n'
	"      </bpmndi:BPMNShape>\n"
	"    "
)

PROMPT_TOOLS = "list_files, read_file, edit_file, write_file, run_tests, open_pull_request"
PROMPT_TOOLS_WITH_DELETE = (
	"list_files, read_file, edit_file, write_file, delete_file, run_tests, open_pull_request"
)
PROMPT_WRITE_RULE = "write_file takes the COMPLETE file, never a diff."
PROMPT_WRITE_RULE_WITH_DELETE = "write_file takes the COMPLETE file, never a diff, and never empty content: to remove a file, call delete_file."

CASE_TITLE = "A file to remove is deleted with delete_file, never emptied with write_file"
CASE_PAYLOAD = {
	"instruction": "Remove spiff/src/components/EditorSidebar.vue. Nothing imports it any more.",
	"work_item": "Remove the unused EditorSidebar component",
	"target_app": "one_bpmn",
	"git_branch": "staging",
}


def execute():
	_edit_named(WRITE_FILE, [(WRITE_CONTENT_CHECK, WRITE_EMPTY_CHECK)])
	if not frappe.db.exists("Server Script", WRITE_FILE):
		return
	_add_delete_script()
	if not (
		frappe.db.exists("AI Agent Configuration", AGENT) and frappe.db.exists("BPMN Process Model", MAP)
	):
		return
	_add_delete_shape()
	_name_delete_in_prompt()
	_add_baseline_case()


def _add_delete_script():
	if frappe.db.exists("Server Script", DELETE_FILE):
		return
	frappe.get_doc(
		{"doctype": "Server Script", "name": DELETE_FILE, "script_type": "API", "script": DELETE_FILE_SCRIPT}
	).insert(ignore_permissions=True)


def _add_delete_shape():
	"""Put delete_file beside the other sandbox tools in the map's ad-hoc sub-process, then recompile the map."""
	from one_bpmn.api.compilation import compile_process_model

	model = frappe.get_doc("BPMN Process Model", MAP)
	xml = model.bpmn_xml or ""
	if 'id="delete_file"' in xml:
		return
	if xml.count("</bpmn:adHocSubProcess>") != 1 or xml.count("</bpmndi:BPMNPlane>") != 1:
		frappe.log_error(
			title="frontend_agent_deletes_files: map shape not added",
			message=f"{MAP} does not have exactly one ad-hoc sub-process and one diagram plane; delete_file was not added.",
		)
		return
	params = json.dumps(TOOL_PARAMS).replace("&", "&amp;").replace('"', "&#34;").replace("'", "&#39;")
	xml = xml.replace(
		"</bpmn:adHocSubProcess>", DELETE_SHAPE.format(params=params) + "</bpmn:adHocSubProcess>"
	)
	xml = xml.replace("</bpmndi:BPMNPlane>", DELETE_SHAPE_DI + "</bpmndi:BPMNPlane>")
	model.bpmn_xml = xml
	model.save(ignore_permissions=True)
	compile_process_model(MAP)


def _name_delete_in_prompt():
	config = frappe.get_doc("AI Agent Configuration", AGENT)
	prompt = config.system_prompt or ""
	for anchor, replacement in (
		(PROMPT_TOOLS, PROMPT_TOOLS_WITH_DELETE),
		(PROMPT_WRITE_RULE, PROMPT_WRITE_RULE_WITH_DELETE),
	):
		if replacement not in prompt and prompt.count(anchor) == 1:
			prompt = prompt.replace(anchor, replacement)
	if prompt != config.system_prompt:
		config.system_prompt = prompt
		config.save(ignore_permissions=True)


def _add_baseline_case():
	suite = _suite()
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": CASE_TITLE}, "name")
	task = _fixture_task(existing, CASE_PAYLOAD)
	case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
	case.suite = suite
	case.title = CASE_TITLE
	case.process_model = MAP
	case.bpmn_id = SHAPE
	case.input_user_prompt = CASE_PAYLOAD["instruction"]
	case.input_context = json.dumps({"context_doctype": "A2A Task", "context_docname": task})
	case.set(
		"assertions",
		[
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
			{"assertion_type": "no_tool_call", "value": "write_file"},
		],
	)
	case.set(
		"expected_tool_calls",
		[
			{
				"call_order": 1,
				"tool_name": "delete_file",
				"argument": "path",
				"matcher": "equals",
				"expected_value": "spiff/src/components/EditorSidebar.vue",
			}
		],
	)
	if existing:
		case.save(ignore_permissions=True)
	else:
		case.insert(ignore_permissions=True)
