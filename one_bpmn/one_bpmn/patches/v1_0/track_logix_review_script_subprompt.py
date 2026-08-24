import frappe

SCRIPT_NAME = "Logix – Tool Review Script"

# Only the import line + the turn/_cfg/_adapter setup block change — the AST
# optimizer and security-gate logic that make up most of this script are
# untouched.
OLD_IMPORTS = (
	'from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn\n'
	'from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings\n'
	'from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config\n'
	'from one_bpmn.security.script_validator import validate_script as _security_validate_script\n'
)
NEW_IMPORTS = (
	'from one_bpmn.agents.turn_state import get_turn, update_turn\n'
	'from one_bpmn.agents.shape_tools import execute_shape\n'
	'from one_bpmn.security.script_validator import validate_script as _security_validate_script\n'
)

OLD_CALL = (
	'turn = get_turn(context_docname)\n'
	'_cfg = get_agent_config("logix_agent") or {}\n'
	'_cfg.setdefault("agent_id", "logix_agent")\n'
	'_subs = _cfg.get("sub_prompts") or {}\n'
	'_adapter = get_llm_adapter_from_settings(_cfg)\n'
	'\n'
	'draft = turn.get("draft", "")\n'
	'shape_kind = turn.get("shape_kind") or (turn.get("process_context") or {}).get("shape_kind") or "script_task"\n'
	'_system = (_subs.get("script_reviewer") or {}).get("prompt") or ""\n'
	'review_raw = run_sync(_adapter.complete(system=_system, user="Shape kind: " + shape_kind + "\\n\\n" + draft)).text\n'
)
NEW_CALL = (
	'turn = get_turn(context_docname)\n'
	'\n'
	'draft = turn.get("draft", "")\n'
	'shape_kind = turn.get("shape_kind") or (turn.get("process_context") or {}).get("shape_kind") or "script_task"\n'
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": "Logix",\n'
	'    "aiSubPromptKey": "script_reviewer",\n'
	'    "aiUserPromptRaw": "Shape kind: " + shape_kind + "\\n\\n" + draft,\n'
	'    "aiBackend": "direct_api",\n'
	'    "aiResponseFormat": "text",\n'
	'    "aiMaxTokens": 4096,\n'
	'    "aiTimeout": 60,\n'
	'    "aiMaxRetries": 2,\n'
	'}\n'
	'review_raw = json.loads(\n'
	'    execute_shape(instance, "review_script", _llm_task_cfg, {})\n'
	').get("review_script_output", "") or ""\n'
)


def execute():
	"""Route review_script's sub-prompt LLM call through execute_shape so it
	gets a tracked AI Agent Run/Step instead of calling the adapter directly
	and unlogged. The AST-based optimizer and security gate are untouched.
	Fourth of six pipeline-stage tools.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return

	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""

	if "execute_shape" in script:
		return  # already migrated

	if OLD_IMPORTS not in script or OLD_CALL not in script:
		frappe.log_error(
			title="track_logix_review_script_subprompt: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; "
			"apply the execute_shape rewrite manually.",
		)
		return

	script = script.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
	script = script.replace(OLD_CALL, NEW_CALL, 1)

	doc.script = script
	doc.save(ignore_permissions=True)
