import frappe

SCRIPT_NAME = "Logix – Tool Write Agent Tool"

# The dedicated config always exists once created, so drop the seeded/unseeded fallback entirely.
OLD = (
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
)
NEW = (
	'_llm_task_cfg = {\n'
	'    "serviceType": "ai_agent",\n'
	'    "aiAgentConfig": ai_sub_agent_config,\n'
)

OLD_TRAILER = 'result["role_used"] = role\n'
NEW_TRAILER = ''


def execute():
	"""Point at the dedicated Logix – Tool Writer (Agent Tools) config instead
	of the shared Logix config's Sub Prompts row being retired, and drop the
	now-pointless seeded/unseeded role fallback. Must run after
	create_logix_stage_agent_configs and add_logix_stage_shape_configs.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return
	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""
	if "ai_sub_agent_config" in script:
		return  # already migrated
	if OLD not in script or OLD_TRAILER not in script:
		frappe.log_error(
			title="switch_logix_write_agent_tool_to_dedicated_config: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; migrate manually.",
		)
		return
	script = script.replace(OLD, NEW, 1)
	script = script.replace(OLD_TRAILER, NEW_TRAILER, 1)
	doc.script = script
	doc.save(ignore_permissions=True)
