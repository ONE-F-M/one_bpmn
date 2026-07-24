"""
WI-001622: create the AI Assistant as the first chat agent stood up through
the agent-creation process.

Seeds an AI Agent Configuration for the assistant (its system prompt taken
from the existing ai_assistant builder, so there is one source of the text),
then runs provision_agent so the same Draft -> Validating -> Provisioning ->
Live path that every future agent uses is proven on this one. Idempotent.
"""

import frappe

AGENT_ID = "ai_agent_assistant"
AGENT_NAME = "AI Agent Assistant"
CHAT_MODE_LABEL = "AI Assistant"


def execute():
	if not frappe.db.exists("DocType", "AI Agent Configuration"):
		return

	try:
		from one_bpmn.api.ai_assistant import _build_system_prompt

		system_prompt = _build_system_prompt()
	except Exception:
		system_prompt = (
			"You are a configuration assistant embedded in the Processa BPMN editor. "
			"You help a process designer configure an AI Agent Task."
		)

	# pick an enabled Anthropic credentials record if one exists, else any enabled
	credentials = frappe.db.get_value("AI Provider Credentials", {"provider_type": "Anthropic", "enabled": 1}, "name") \
		or frappe.db.get_value("AI Provider Credentials", {"enabled": 1}, "name")

	if frappe.db.exists("AI Agent Configuration", {"agent_id": AGENT_ID}):
		doc = frappe.get_doc("AI Agent Configuration", {"agent_id": AGENT_ID})
	else:
		doc = frappe.new_doc("AI Agent Configuration")
		doc.agent_name = AGENT_NAME
		doc.agent_id = AGENT_ID

	doc.agent_framework = "Direct API"
	doc.agent_type = "Chat"
	doc.enabled = 1
	doc.chat_mode_label = CHAT_MODE_LABEL
	doc.icon = "🛠️"
	doc.chat_description = "Helps configure AI Agent Task and Selector shapes on the canvas."
	doc.system_prompt = system_prompt
	if credentials and not doc.ai_provider_credentials:
		doc.ai_provider_credentials = credentials
	doc.set("sample_prompts", [
		{
			"prompt": "Configure an AI task that summarises a Leave Application's reason field.",
			"expected_behaviour": "Recommends an aiUserPrompt using {{ doc.reason }} and a snake_case aiOutputVariable.",
		},
	])
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()

	# Stand it up through the real creation process (patch context suppresses
	# the after_insert auto-trigger, so provision explicitly here).
	try:
		from one_bpmn.agents.agent_provisioning import provision_agent

		provision_agent(doc.name)
	except Exception:
		frappe.log_error(title="seed_ai_assistant_agent: provision failed", message=frappe.get_traceback())
