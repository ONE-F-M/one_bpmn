"""
WI-001630: collapse the two per-provider Lumina configs into one
``lumina_general_chat`` AI Agent Configuration.

General Chat shipped as TWO records — ``lumina_chatbot_openai`` and
``lumina_chatbot_gemini`` — selected by ``AI Chat Settings.llm_provider`` at
runtime, each carrying its own near-duplicate copy of the same system prompt.
Two copies of one agent's prompt is two things to keep in step, and the branching
that chose between them lived in ``onefm_mcp.api`` rather than in the agent
registry.

The two records differ ONLY in:
  * system_prompt — near-identical; the OpenAI copy is authoritative because
    ``llm_provider`` is 'openai', so it is the text actually serving users.
  * description.
  * constants — chat_history_limit 10 (OpenAI) vs 5 (Gemini), max_tool_recursion
    5 in both, plus a Gemini-only ``acknowledgment_text``.

So the merge keeps the OpenAI prompt, OpenAI's chat_history_limit, and carries
``acknowledgment_text`` forward regardless: the Gemini path still reads it while
it exists, and preserving it costs nothing.

The two old records are DISABLED, not deleted — they are the audit trail of what
the agent used to be, and Frappe links (AI Agent Run history, observability) still
point at them.

Deliberately NOT done here:
  * The process map is not installed. Maps and their Server Scripts travel by
    Processa export/import; only this record needs a patch.
  * ``process_model`` is asserted only if the map already exists on the site, so
    this patch is safe to run before the map is imported and again after.

Go-live: the record is promoted only when ``validate_agent_config`` passes, which
includes a LIVE provider test call. On a site whose OpenAI credentials carry no
API key that test fails by design and the agent lands in Needs Attention with the
reason recorded — which is the correct outcome, not a silent Live.
"""

import frappe

AGENT_ID = "lumina_general_chat"
AGENT_NAME = "Lumina General Chat"
CHAT_LABEL = "General Chat"
ICON = "💬"
PROCESS_MODEL = "Lumina Chat – General Agent"
AI_MODEL = "gpt-5-nano"
TEMPERATURE = 0.3
# api.py's MAX_TOKENS. A configuration's max_tokens is authoritative at dispatch
# and 0 resolves to the 1024 default there — far below what General Chat answers
# with today, so leaving it unset would silently truncate long replies.
MAX_TOKENS = 10000

RETIRED = ("lumina_chatbot_openai", "lumina_chatbot_gemini")

# The prompt that actually serves General Chat today (the OpenAI copy), carried
# over verbatim so reply behaviour is unchanged. NOTE: `{current_datetime}` is a
# str.format placeholder filled by the direct-API path. If/when the turn moves
# onto the process map, the map renders prompts with Jinja instead and this must
# become `{{ frappe.utils.now_datetime() }}` — the two syntaxes cannot both work
# from one string.
SYSTEM_PROMPT = """You are a helpful AI assistant integrated with Frappe/ERPNext. You are friendly, professional, and conversational.
Current datetime: {current_datetime}

CORE BEHAVIOR:
- Speak naturally as if you're a helpful colleague
- Be warm, professional, and solution-focused
- Present information clearly without technical jargon
- Always respect user permissions and roles
- Carefully read any text content present in attached images.
- Incorporate the extracted text into your response.

TOOL INTEGRATION:
- When tools provide results, incorporate them naturally into responses
- Present information as if you personally performed the task
- Don't mention technical processes - focus on outcomes
- When the user requests a new report, query report, or SQL-based report generation (e.g., "Create a report for DocType 'X'"), you must follow this exact, non-negotiable workflow:
- **Step 1: Validation.** Call `check_doctype_exists` with the user's specified DocType. If a module is provided, also call `check_module_exists`.
- **Step 2: Handle Failure.** If validation fails (returns `exists: false`), your ONLY permitted action is to inform the user of the invalid DocType or module. Do not proceed.
- **Step 3: Call the Generator Tool.** If validation is successful, your immediate and ONLY next action is to call the `generate_report_query` tool.
-   **Argument Construction for `generate_report_query`:**
-   `ref_doctype`: Use the exact DocType name the user provided.
-   `report_name`: First, check if the user provided a specific name for the report. If they did, use that exact name. If they did NOT provide a name, create a descriptive one by appending "Report" to the `ref_doctype`.
-   `description`: Use the user's full, original prompt as the description.
-   `module`: Use the module name if provided by the user.
- **ABSOLUTE FINAL RULE:** Under no circumstances should you ever respond with a JSON object, SQL query, or any text after a successful validation. Your ONLY valid response is a direct tool call to `generate_report_query`. Any other response is a failure to follow instructions.
- If one tool fails, try alternative approaches before reporting errors
- When using the `search_company_wiki` tool:
-   First, provide your full everyday-language response that explains and applies the wiki content for the user.
-   Then, append the raw output from `search_company_wiki` (the delimited JSON block) exactly as returned by the tool.
-   The wiki JSON block MUST be the absolute last thing in your response; you MUST NOT add any text, labels (like "Sources:" or "Wiki content:"), or follow-up content after the block.

RESPONSE FORMAT:
- Use everyday professional language
- Be conversational and engaging
- Provide clear, actionable insights
- When presenting tabular data (e.g., lists of employees, financial figures), format it as a Markdown table to improve readability.
- Format data appropriately (dates/times for Kuwait timezone)
- Keep responses compact for chat interface

Remember: You're having a conversation, not executing technical commands."""

DESCRIPTION = (
	"Lumina's general-purpose assistant for the Desk chat page: conversational "
	"Frappe/ERPNext help with the MCP tool surface, streaming, and vision support. "
	"Single configuration replacing the former per-provider OpenAI/Gemini pair."
)

CONSTANTS = (
	# name, value, type — chat_history_limit takes OpenAI's 10 (the provider in use).
	("chat_history_limit", "10", "Integer"),
	("max_tool_recursion", "5", "Integer"),
	(
		"acknowledgment_text",
		"I understand. I'm ready to help you with your Frappe/ERPNext tasks using "
		"the available tools while respecting your permissions.",
		"String",
	),
)


def _upsert_config():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if name:
		doc = frappe.get_doc("AI Agent Configuration", name)
	else:
		doc = frappe.new_doc("AI Agent Configuration")
		doc.agent_id = AGENT_ID
		doc.agent_name = AGENT_NAME

	doc.agent_type = "Chat"
	doc.enabled = 1
	# Direct API keeps the generic invocation working before the map exists:
	# _runner_for() prefers a linked process_model and only then the framework.
	doc.agent_framework = "Direct API"
	doc.chat_mode_label = CHAT_LABEL
	doc.icon = doc.icon or ICON
	doc.description = DESCRIPTION
	doc.temperature = TEMPERATURE
	if not doc.max_tokens:
		doc.max_tokens = MAX_TOKENS
	if not doc.system_prompt:
		doc.system_prompt = SYSTEM_PROMPT
	elif doc.system_prompt.strip() != SYSTEM_PROMPT.strip():
		# Own the prompt only while it is still one of the originals; a genuine
		# edit made in the UI is left alone.
		if "You are a helpful AI assistant integrated with Frappe/ERPNext" in doc.system_prompt:
			doc.system_prompt = SYSTEM_PROMPT

	# The model is the pick; ai_provider_credentials follows it on save.
	if not doc.ai_model and frappe.db.exists("AI Model", AI_MODEL):
		doc.ai_model = AI_MODEL

	# Link the map when it is present. Absent on a site that has not imported it
	# yet, in which case the generic path uses the Direct API runner.
	if not doc.process_model and frappe.db.exists("BPMN Process Model", PROCESS_MODEL):
		doc.process_model = PROCESS_MODEL

	# allowed_roles stays EMPTY on purpose: General Chat is offered to every
	# logged-in user today, and an empty table means exactly that (WI-001618).

	existing = {row.constant_name for row in (doc.get("constants") or [])}
	for cname, cvalue, ctype in CONSTANTS:
		if cname in existing:
			continue
		doc.append("constants", {
			"constant_name": cname,
			"constant_value": cvalue,
			"constant_type": ctype,
		})

	doc.save(ignore_permissions=True)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	return doc.name


def _retire_old_configs():
	for agent_id in RETIRED:
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		if not name:
			continue
		if frappe.db.get_value("AI Agent Configuration", name, "enabled"):
			frappe.db.set_value("AI Agent Configuration", name, "enabled", 0, update_modified=False)
		frappe.cache.delete_value(f"agent_config:{agent_id}")


def _go_live(name):
	try:
		from one_bpmn.agents.agent_provisioning import validate_agent_config

		result = validate_agent_config(name, test_provider=True)
	except Exception:
		frappe.log_error(
			title="Lumina General Chat migration: validation raised",
			message=frappe.get_traceback(),
		)
		return

	ok = result.get("ok")
	reason = "\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok"
	frappe.db.set_value(
		"AI Agent Configuration",
		name,
		{
			"lifecycle_status": "Live" if ok else "Needs Attention",
			# Carry the WHY onto the record, not just into the Error Log — the
			# form shows this as its intro banner, and "Needs Attention" with no
			# reason is the least useful state to hand an admin.
			"needs_attention_reason": "" if ok else reason,
		},
		update_modified=False,
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	if not ok:
		frappe.log_error(
			title=f"Lumina General Chat migration: not promoted to Live ({AGENT_ID})",
			message=reason,
		)


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		name = _upsert_config()
		_retire_old_configs()
		frappe.db.commit()
		_go_live(name)
		frappe.db.commit()
	finally:
		frappe.set_user(original_user)
