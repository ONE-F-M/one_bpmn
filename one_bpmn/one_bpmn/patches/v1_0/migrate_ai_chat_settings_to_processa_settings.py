# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002140: fold all of onefm_mcp's AI Chat Settings into Processa Settings,
the site-wide config singleton this repo already uses for cross-cutting
one_bpmn defaults — one settings surface instead of one per app.

This carries across every still-useful field: LangSmith, Langfuse, the token
estimator, the transitional global LLM provider default, and the onefm_mcp-owned
Lumina chat widget / MCP tool / Jira / Copilot config (grouped under Processa
Settings' own "MCP Integration Settings" section rather than a separate
onefm_mcp doctype). AI Chat Settings itself can be dropped once this has run.

`openai_search_context` and `user_story_template` looked unreferenced by any
checked-in code, but production data showed both carrying a real configured
value (an OpenAI search-context tier, and a full BA/User Planning agent story
template) — almost certainly read by a BPMN Script Task node's inline script,
which lives as data on a BPMN Process Model record, not as a file this repo's
grep can see. Migrated rather than dropped for that reason; whatever Script
Task reads them still needs its own update to point at Processa Settings.

Read-only against the source: AI Chat Settings is left alone here, so a failure
is safe to re-run.
"""

import frappe
from frappe.utils.password import get_decrypted_password

FIELD_MAP = {
	"enable_observability": "enable_observability",
	"langsmith_project_name": "langsmith_project_name",
	"observability_sanitization_level": "observability_sanitization_level",
	"observability_retry_attempts": "observability_retry_attempts",
	"langfuse_base_url": "langfuse_base_url",
	"dev_agent_weekly_report_enabled": "dev_agent_weekly_report_enabled",
	"dev_agent_report_recipients": "dev_agent_report_recipients",
	"token_estimator_chars_per_token": "token_estimator_chars_per_token",
	"enabled": "enabled",
	"mcp_tools_enabled": "mcp_tools_enabled",
	"enable_mcp_tools_for_user_planning_agent": "enable_mcp_tools_for_user_planning_agent",
	"jira_url": "jira_url",
	"jira_email": "jira_email",
	"copilot_org_name": "copilot_org_name",
	"copilot_enterprise_slug": "copilot_enterprise_slug",
	"openai_search_context": "openai_search_context",
	"user_story_template": "user_story_template",
}
PASSWORD_FIELD_MAP = {
	"langsmith_api_key": "langsmith_api_key",
	"langfuse_public_key": "langfuse_public_key",
	"langfuse_secret_key": "langfuse_secret_key",
	"jira_api_token": "jira_api_token",
	"copilot_metrics_pat": "copilot_metrics_pat",
}


def execute():
	if not frappe.db.exists("DocType", "Processa Settings"):
		return  # the fields ship with this change; nothing to do until synced

	if not frappe.db.exists("DocType", "AI Chat Settings"):
		return  # onefm_mcp not installed, or already retired on this site

	source = frappe.db.get_value("AI Chat Settings", "AI Chat Settings", "name")
	if not source:
		return

	settings = frappe.get_single("Processa Settings")
	copied = []

	default_provider = frappe.db.get_value(
		"AI Chat Settings", "AI Chat Settings", "processa_llm_provider"
	) or frappe.db.get_value("AI Chat Settings", "AI Chat Settings", "llm_provider")
	if default_provider:
		settings.default_llm_provider = default_provider
		copied.append("default_llm_provider")

	source_values = frappe.db.get_value(
		"AI Chat Settings", "AI Chat Settings", list(FIELD_MAP.keys()), as_dict=True
	) or {}
	for src_field, dest_field in FIELD_MAP.items():
		value = source_values.get(src_field)
		if value is not None and value != "":
			settings.set(dest_field, value)
			copied.append(dest_field)

	for src_field, dest_field in PASSWORD_FIELD_MAP.items():
		value = get_decrypted_password(
			"AI Chat Settings", "AI Chat Settings", src_field, raise_exception=False
		)
		if value:
			settings.set(dest_field, value)
			copied.append(dest_field)

	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)
	_repoint_langfuse_report_task()
	frappe.db.commit()

	print(f"Processa Settings: migrated {len(copied)} field(s) from AI Chat Settings — {', '.join(copied) or 'none'}")


def _repoint_langfuse_report_task():
	"""The weekly Langfuse report's tracking record still tags itself
	against "AI Chat Settings" (see onefm_mcp's create_langfuse_report_process_task
	patch); point it at the doctype that now actually holds those credentials.
	Best-effort — the Process Task/Method doctypes belong to onefm_mcp/one_fm's
	own task-tracking system, not to one_bpmn.
	"""
	if not frappe.db.exists("DocType", "Method"):
		return

	method = "onefm_mcp.utils.langfuse_report.generate_weekly_report"
	if frappe.db.exists("Method", method):
		frappe.db.set_value("Method", method, "document_type", "Processa Settings", update_modified=False)

	if frappe.db.exists("DocType", "Process Task"):
		frappe.db.set_value(
			"Process Task",
			{"method": method, "erp_document": "AI Chat Settings"},
			"erp_document",
			"Processa Settings",
			update_modified=False,
		)
