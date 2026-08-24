import frappe

SCRIPT_NAME = "Logix – Tool Classify Intent"

OLD = (
	'    "aiAgentConfig": "Logix",\n'
	'    "aiSubPromptKey": "intent_classifier",\n'
)
NEW = '    "aiAgentConfig": ai_sub_agent_config,\n'


def execute():
	"""Point at the dedicated Logix – Intent Classifier config (via the
	spiffworkflow:aiSubAgentConfig shape attribute, injected as
	ai_sub_agent_config) instead of the shared Logix config's Sub Prompts row
	being retired. Must run after create_logix_stage_agent_configs and
	add_logix_stage_shape_configs.
	"""
	if not frappe.db.exists("Server Script", SCRIPT_NAME):
		return
	doc = frappe.get_doc("Server Script", SCRIPT_NAME)
	script = doc.script or ""
	if "ai_sub_agent_config" in script:
		return  # already migrated
	if OLD not in script:
		frappe.log_error(
			title="switch_logix_classify_intent_to_dedicated_config: anchor not found",
			message=f"'{SCRIPT_NAME}' diverged from the expected body; migrate manually.",
		)
		return
	doc.script = script.replace(OLD, NEW, 1)
	doc.save(ignore_permissions=True)
