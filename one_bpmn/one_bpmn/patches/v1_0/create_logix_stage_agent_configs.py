import frappe

PARENT_CONFIG = "Logix"

# sub_agent_id -> new dedicated AI Agent Configuration's agent_id.
NEW_AGENT_IDS = {
	"intent_classifier": "logix_intent_classifier",
	"clarifier": "logix_clarifier",
	"script_writer": "logix_script_writer",
	"script_reviewer": "logix_script_reviewer",
	"test_writer": "logix_test_writer",
	"tool_writer": "logix_tool_writer",
}


def execute():
	"""Give each Logix pipeline-stage tool its own standalone AI Agent
	Configuration, sourced from the existing Sub Prompts row, so the Script
	Task properties panel can link to a real record instead of a table row
	(the Sub Prompts table is being removed). Reads live data rather than
	hardcoding prompt text, so nothing is retyped or drifts from what's
	actually configured today.
	"""
	if not frappe.db.exists("AI Agent Configuration", PARENT_CONFIG):
		return

	parent = frappe.get_doc("AI Agent Configuration", PARENT_CONFIG)
	rows = frappe.get_all(
		"AI Agent Sub Prompt",
		filters={"parent": PARENT_CONFIG, "parenttype": "AI Agent Configuration"},
		fields=["sub_agent_id", "sub_agent_name", "prompt_text", "temperature"],
	)
	if not rows:
		return

	for row in rows:
		agent_name = f"Logix – {row.sub_agent_name}"
		if frappe.db.exists("AI Agent Configuration", agent_name):
			continue  # already migrated

		agent_id = NEW_AGENT_IDS.get(row.sub_agent_id)
		if not agent_id:
			frappe.log_error(
				title="create_logix_stage_agent_configs: unmapped sub_agent_id",
				message=f"'{row.sub_agent_id}' has no entry in NEW_AGENT_IDS; skipped.",
			)
			continue

		doc = frappe.new_doc("AI Agent Configuration")
		doc.agent_name = agent_name
		doc.agent_id = agent_id
		doc.agent_framework = "Direct API"
		doc.agent_type = "Background"
		doc.system_prompt = row.prompt_text
		doc.temperature = row.temperature or parent.temperature
		doc.ai_model = parent.ai_model
		doc.ai_provider_credentials = parent.ai_provider_credentials
		doc.enabled = 1
		doc.insert(ignore_permissions=True)
