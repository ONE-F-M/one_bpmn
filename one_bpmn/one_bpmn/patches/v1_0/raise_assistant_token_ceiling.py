"""
WI-001751 follow-up: give the AI Assistant an output budget it can finish in.

Symptom: asked to create an eval suite with four cases, the assistant replied
"I could not generate a response. Please try again." The AI Agent Run recorded
Success with no error, and its assistant step showed completion_tokens = 1024 —
exactly at a ceiling.

Cause: dispatchers.py reads ``int(task_cfg.get("aiMaxTokens", 1024) or 1024)``.
The assistant's task shape carries aiMaxTokens=0 and its configuration's
max_tokens was 0, and ``0 or 1024`` is 1024. So every assistant reply was capped
at 1024 output tokens.

That was survivable while replies were prose or a small tool call. It stopped
being survivable when create_eval_suite gained its ``cases`` argument
(add_eval_suite_inline_cases): a suite with four cases and their assertions is a
single tool call whose JSON arguments exceed 1024 tokens on their own, so the
call is cut off mid-argument and nothing downstream can parse it.

Fix: set max_tokens on the assistant's configuration. The configuration is
authoritative at dispatch (resolve_dispatch_overrides maps max_tokens ->
aiMaxTokens) and config_field_map skips empty values, so a non-zero value here
overrides the shape's 0 without touching the diagram.

16384 matches the adapters' own default for a direct call. It is a ceiling, not
an allocation — ordinary short replies cost exactly what they did before.

Only the assistant is changed. Other agents keep whatever they were configured
with; the 1024 fallback in dispatchers.py is a separate question, since raising
it would change behaviour for every AI task on every site.
"""

import frappe

AGENT_ID = "ai_agent_assistant"
MAX_TOKENS = 16384


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		frappe.log_error(
			title="raise_assistant_token_ceiling: assistant config missing",
			message=f"No AI Agent Configuration with agent_id '{AGENT_ID}' on this site.",
		)
		return

	current = frappe.db.get_value("AI Agent Configuration", name, "max_tokens") or 0
	# Only raise. A site that has deliberately set a higher ceiling keeps it.
	if int(current) >= MAX_TOKENS:
		return

	frappe.db.set_value(
		"AI Agent Configuration", name, "max_tokens", MAX_TOKENS, update_modified=False
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	frappe.db.commit()
