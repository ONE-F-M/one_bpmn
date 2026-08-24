import frappe

SCRIPT_NAME = "Logix – Tool Write Agent Tool"

OLD_SETUP = (
	'import re\n'
	'from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn\n'
	'from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings\n'
	'from one_bpmn.agents.llm_provider.base import ToolSpec\n'
	'from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config\n'
	'from one_bpmn.tools.tool_for_server_scripts import (\n'
	'    get_doctype_fields,\n'
	'    get_server_script_content,\n'
	'    get_server_script_meta,\n'
	'    list_api_server_scripts,\n'
	')\n'
	'\n'
	'turn = get_turn(context_docname)\n'
	'_cfg = get_agent_config("logix_agent") or {}\n'
	'_cfg.setdefault("agent_id", "logix_agent")\n'
	'_subs = _cfg.get("sub_prompts") or {}\n'
	'_adapter = get_llm_adapter_from_settings(_cfg)\n'
)
NEW_SETUP = (
	'import json\n'
	'import re\n'
	'from one_bpmn.agents.turn_state import get_turn, update_turn\n'
	'from one_bpmn.agents.llm_provider.base import ToolSpec\n'
	'from one_bpmn.agents.shape_tools import execute_shape\n'
	'from one_bpmn.tools.tool_for_server_scripts import (\n'
	'    get_doctype_fields,\n'
	'    get_server_script_content,\n'
	'    get_server_script_meta,\n'
	'    list_api_server_scripts,\n'
	')\n'
	'\n'
	'turn = get_turn(context_docname)\n'
)

# The role fallback now uses one existence query instead of reading _subs directly.
OLD_CALL = (
	'# The specialist tool_writer sub-agent owns the Agent Tool standard; fall back to\n'
	'# the general dual-contract writer if the sub-prompt is not seeded yet.\n'
	'role = "tool_writer" if (_subs.get("tool_writer") or {}).get("prompt") else "script_writer"\n'
	'_system = (_subs.get(role) or {}).get("prompt") or ""\n'
	'draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text\n'
)
NEW_CALL = (
	'# The specialist tool_writer sub-agent owns the Agent Tool standard; fall back to\n'
	'# the general dual-contract writer if the sub-prompt is not seeded yet.\n'
	'role = "tool_writer" if frappe.db.exists(\n'
	'    "AI Agent Sub Prompt",\n'
	'    {"parent": "Logix", "parenttype": "AI Agent Configuration", "sub_agent_id": "tool_writer"},\n'
	') else "script_writer"\n'
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": "Logix",\n'
	'    "aiSubPromptKey": role,\n'
	'    "aiUserPromptRaw": prompt,\n'
	'    "aiToolSpecs": _writer_tools,\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiMaxTokens": 4096,\n'
	'    "aiTimeout": 60,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'draft = json.loads(\n'
	'    execute_shape(instance, "write_agent_tool", _llm_task_cfg, {})\n'
	').get("write_agent_tool_output", "") or ""\n'
)


def execute():
	"""Route write_agent_tool's sub-prompt LLM call through execute_shape so
	it gets a tracked AI Agent Run/Step instead of calling the adapter
	directly and unlogged. Diagram and tool description are unchanged —
	Server Script body only. Fifth of six pipeline-stage tools.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return

	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""

	if "execute_shape" in script:
		return  # already migrated

	if OLD_SETUP not in script or OLD_CALL not in script:
		frappe.log_error(
			title="track_logix_write_agent_tool_subprompt: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; "
			"apply the execute_shape rewrite manually.",
		)
		return

	script = script.replace(OLD_SETUP, NEW_SETUP, 1)
	script = script.replace(OLD_CALL, NEW_CALL, 1)

	doc.script = script
	doc.save(ignore_permissions=True)
