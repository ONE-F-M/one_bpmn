import frappe

SCRIPT_NAME = "Logix – Tool Clarify"

OLD_SETUP = (
	'import json\n'
	'import re\n'
	'from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn\n'
	'from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings\n'
	'from one_bpmn.agents.llm_provider.base import ToolSpec\n'
	'from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config\n'
	'from one_bpmn.tools.tool_for_server_scripts import get_server_script_meta, list_api_server_scripts\n'
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
	'from one_bpmn.tools.tool_for_server_scripts import get_server_script_meta, list_api_server_scripts\n'
	'\n'
	'turn = get_turn(context_docname)\n'
)

# The clarifier's nested tools ride through via aiToolSpecs, not aiToolShapes.
OLD_CALL = (
	'_system = (_subs.get("clarifier") or {}).get("prompt") or ""\n'
	'raw = run_sync(_adapter.complete(system=_system, user=prompt, tools=_clarifier_tools)).text\n'
)
NEW_CALL = (
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": "Logix",\n'
	'    "aiSubPromptKey": "clarifier",\n'
	'    "aiUserPromptRaw": prompt,\n'
	'    "aiToolSpecs": _clarifier_tools,\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiMaxTokens": 512,\n'
	'    "aiTimeout": 30,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'raw = json.loads(\n'
	'    execute_shape(instance, "clarify", _llm_task_cfg, {})\n'
	').get("clarify_output", "") or ""\n'
)


def execute():
	"""Route clarify's sub-prompt LLM call through execute_shape so it gets a
	tracked AI Agent Run/Step instead of calling the adapter directly and
	unlogged. Diagram and tool description are unchanged — Server Script body
	only. Second of six pipeline-stage tools (classify_intent already done).
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return

	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""

	if "execute_shape" in script:
		return  # already migrated

	if OLD_SETUP not in script or OLD_CALL not in script:
		frappe.log_error(
			title="track_logix_clarify_subprompt: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; "
			"apply the execute_shape rewrite manually.",
		)
		return

	script = script.replace(OLD_SETUP, NEW_SETUP, 1)
	script = script.replace(OLD_CALL, NEW_CALL, 1)

	doc.script = script
	doc.save(ignore_permissions=True)
