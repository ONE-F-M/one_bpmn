"""Logix's fixed turn rules join its system prompt, so they are served from the prompt cache. Idempotent.

The Run Logix Agent user prompt still carries the rules; drop_duplicated_instructions removes a user
prompt paragraph that the system prompt already holds, so the map needs no edit.
"""

import frappe

AGENT = "Logix"
EM_DASH = chr(0x2014)
# Verbatim from the Run Logix Agent aiUserPrompt; the duplicate is only dropped on an exact match.
TURN_RULES = (
	"The user's message is at the end of this prompt, and your tools read the conversation server-side, "
	"so NEVER ask them to repeat or provide it. HARD PIPELINE RULES: (1) ALWAYS call classify_intent first; "
	"it reads the user's message server-side and returns the intent plus a next field. (2) Follow next: "
	"write_script for CREATE or MODIFY, review_script after every write, clarify for DISAMBIGUATE. "
	f"(3) Every turn MUST end by calling finalize {EM_DASH} what finalize produces is the ONLY thing the user "
	"ever sees. (4) Never answer in plain text: text outside tool calls is discarded and the user sees an "
	"error instead of your words."
)


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT):
		return
	prompt, agent_id = frappe.db.get_value("AI Agent Configuration", AGENT, ["system_prompt", "agent_id"])
	if not prompt or TURN_RULES in prompt:
		return
	frappe.db.set_value(
		"AI Agent Configuration", AGENT, "system_prompt", f"{prompt.rstrip()}\n\n{TURN_RULES}"
	)
	frappe.cache.delete_value(f"agent_config:{agent_id}")
