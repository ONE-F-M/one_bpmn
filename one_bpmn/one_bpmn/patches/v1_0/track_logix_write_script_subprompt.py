import frappe

SCRIPT_NAME = "Logix – Tool Write Script"

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

OLD_CALL = (
	'_system = (_subs.get("script_writer") or {}).get("prompt") or ""\n'
	'draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text\n'
)
NEW_CALL = (
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": "Logix",\n'
	'    "aiSubPromptKey": "script_writer",\n'
	'    "aiUserPromptRaw": prompt,\n'
	'    "aiToolSpecs": _writer_tools,\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiMaxTokens": 4096,\n'
	'    "aiTimeout": 60,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'draft = json.loads(\n'
	'    execute_shape(instance, "write_script", _llm_task_cfg, {})\n'
	').get("write_script_output", "") or ""\n'
)


def execute():
	"""Route write_script's sub-prompt LLM call through execute_shape so it
	gets a tracked AI Agent Run/Step instead of calling the adapter directly
	and unlogged. Diagram and tool description are unchanged — Server Script
	body only. Third of six pipeline-stage tools.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return

	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""

	if "execute_shape" in script:
		return  # already migrated

	if OLD_SETUP not in script or OLD_CALL not in script:
		frappe.log_error(
			title="track_logix_write_script_subprompt: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; "
			"apply the execute_shape rewrite manually.",
		)
		return

	script = script.replace(OLD_SETUP, NEW_SETUP, 1)
	script = script.replace(OLD_CALL, NEW_CALL, 1)

	doc.script = script
	doc.save(ignore_permissions=True)
