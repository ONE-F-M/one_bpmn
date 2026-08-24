import frappe

SCRIPT_NAME = "Logix – Tool Classify Intent"

# The setup block: dropped once the LLM call itself moves to execute_shape,
# since _cfg/_subs/_adapter existed only to feed that call.
OLD_SETUP = (
	'import json\n'
	'import re\n'
	'from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn\n'
	'from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings\n'
	'from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config\n'
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
	'from one_bpmn.agents.shape_tools import execute_shape\n'
	'\n'
	'turn = get_turn(context_docname)\n'
)

# Now goes through execute_shape -> dispatch_ai_agent for a tracked AI Agent Run.
OLD_CALL = (
	'_system = (_subs.get("intent_classifier") or {}).get("prompt") or ""\n'
	'raw = run_sync(_adapter.complete(system=_system, user=prompt)).text\n'
)
NEW_CALL = (
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": "Logix",\n'
	'    "aiSubPromptKey": "intent_classifier",\n'
	'    "aiUserPromptRaw": prompt,\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiMaxTokens": 512,\n'
	'    "aiTimeout": 30,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'raw = json.loads(\n'
	'    execute_shape(instance, "classify_intent", _llm_task_cfg, {})\n'
	').get("classify_intent_output", "") or ""\n'
)


def execute():
	"""Route classify_intent's sub-prompt LLM call through execute_shape so it
	gets a tracked AI Agent Run/Step instead of calling the adapter directly
	and unlogged. Diagram and tool description are unchanged — this only
	edits the Server Script body. Pilot for the same change on the other
	pipeline-stage tools (clarify, write_script, review_script,
	write_agent_tool, finalize) once verified.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return

	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""

	if "execute_shape" in script:
		return  # already migrated

	if OLD_SETUP not in script or OLD_CALL not in script:
		frappe.log_error(
			title="track_logix_classify_intent_subprompt: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; "
			"apply the execute_shape rewrite manually.",
		)
		return

	script = script.replace(OLD_SETUP, NEW_SETUP, 1)
	script = script.replace(OLD_CALL, NEW_CALL, 1)

	doc.script = script
	doc.save(ignore_permissions=True)
