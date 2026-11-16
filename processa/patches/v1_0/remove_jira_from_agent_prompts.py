"""Remove the Jira instructions and create_jira_stories from the BA agent prompts."""

import frappe

EDITS = {
	"BA Agent": (
		(" \u2014 Jira rejects longer.", "."),
		(
			"\n\nJIRA. Only when the user explicitly asks for it (their message mentions Jira),\n"
			"call `create_jira_stories` with EVERY story in the list, then report what was\n"
			"created in `response`. Never create Jira issues on your own initiative.",
			"",
		),
	),
	"BA Product Manager": (
		("10. **JIRA COMPATIBILITY**:", "10. **SUMMARY LENGTH**:"),
		(
			"**JIRA INTEGRATION:**\n"
			'If (AND ONLY IF) the user explicitly specifies "Create these stories in Jira" in their latest '
			"message, you MUST call the `create_jira_stories` tool.\n"
			"- **Trigger**: Latest message contains 'jira'.\n"
			"- **Action**: Call `create_jira_stories` with the list of ALL generated user stories.\n"
			"- **IMPORTANT**: Ensure the `stories` list passed to the tool contains every single user story you "
			"have just generated. DO NOT output any text. JUST call the tool.\n\n",
			"",
		),
	),
}


def execute():
	for config, edits in EDITS.items():
		prompt = frappe.db.get_value("AI Agent Configuration", config, "system_prompt")
		if not prompt:
			continue
		edited = prompt
		for old, new in edits:
			edited = edited.replace(old, new)
		if edited == prompt:
			continue
		frappe.db.set_value("AI Agent Configuration", config, "system_prompt", edited, update_modified=False)
		agent_id = frappe.db.get_value("AI Agent Configuration", config, "agent_id")
		frappe.cache.delete_value(f"agent_config:{agent_id}")
