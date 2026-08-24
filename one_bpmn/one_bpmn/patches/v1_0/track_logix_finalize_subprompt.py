import frappe

SCRIPT_NAME = "Logix – Tool Finalize"

# finalize only calls an LLM in one branch (the CREATE-with-code test-checklist
# generator, a "bonus" that never fails the turn) — every other branch
# (clarify passthrough, refusal, question passthrough, MODIFY diff) is purely
# deterministic and untouched.
OLD_IMPORTS = (
	'from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn\n'
	'from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings\n'
	'from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config\n'
)
NEW_IMPORTS = (
	'from one_bpmn.agents.turn_state import get_turn, update_turn\n'
	'from one_bpmn.agents.shape_tools import execute_shape\n'
)

OLD_SETUP = (
	'                checklist = []\n'
	'                _cfg = get_agent_config("logix_agent") or {}\n'
	'                _cfg.setdefault("agent_id", "logix_agent")\n'
	'                _subs = _cfg.get("sub_prompts") or {}\n'
	'                _adapter = get_llm_adapter_from_settings(_cfg)\n'
	'                element_name = turn.get("element_name", "")\n'
)
NEW_SETUP = (
	'                checklist = []\n'
	'                element_name = turn.get("element_name", "")\n'
)

OLD_CALL = (
	'                try:\n'
	'                    _tsys = (_subs.get("test_writer") or {}).get("prompt") or ""\n'
	'                    test_raw = run_sync(_adapter.complete(system=_tsys, user=test_prompt)).text or ""\n'
	'                    _stripped = test_raw.strip()\n'
)
NEW_CALL = (
	'                try:\n'
	'                    _llm_task_cfg = {\n'
	'                        "serviceType": "ai_agent",\n'
	'                        "aiAgentConfig": "Logix",\n'
	'                        "aiSubPromptKey": "test_writer",\n'
	'                        "aiUserPromptRaw": test_prompt,\n'
	'                        "aiBackend": "direct_api",\n'
	'                        "aiResponseFormat": "text",\n'
	'                        "aiMaxTokens": 1024,\n'
	'                        "aiTimeout": 30,\n'
	'                        "aiMaxRetries": 2,\n'
	'                    }\n'
	'                    test_raw = json.loads(\n'
	'                        execute_shape(instance, "finalize", _llm_task_cfg, {})\n'
	'                    ).get("finalize_output", "") or ""\n'
	'                    _stripped = test_raw.strip()\n'
)


def execute():
	"""Route finalize's test_writer sub-prompt LLM call through execute_shape
	so it gets a tracked AI Agent Run/Step instead of calling the adapter
	directly and unlogged. Every deterministic branch (refusal, passthrough,
	diff) is untouched. Sixth and last of the pipeline-stage tools.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return

	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""

	if "execute_shape" in script:
		return  # already migrated

	if OLD_IMPORTS not in script or OLD_SETUP not in script or OLD_CALL not in script:
		frappe.log_error(
			title="track_logix_finalize_subprompt: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; "
			"apply the execute_shape rewrite manually.",
		)
		return

	script = script.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
	script = script.replace(OLD_SETUP, NEW_SETUP, 1)
	script = script.replace(OLD_CALL, NEW_CALL, 1)

	doc.script = script
	doc.save(ignore_permissions=True)
