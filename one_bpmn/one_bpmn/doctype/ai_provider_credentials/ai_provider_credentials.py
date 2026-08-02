# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _




from frappe.model.document import Document


class AIProviderCredentials(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        api_endpoint: DF.Data | None
        api_key: DF.Password
        default_model: DF.Data | None
        enabled: DF.Check
        provider_name: DF.Data
        provider_type: DF.Literal["OpenAI", "Anthropic", "Google", "Bedrock", "OpenAI-compatible", "Antigravity"]
    # end: auto-generated types
    pass


@frappe.whitelist()
def test_connection(provider_name: str) -> dict:
	"""
	Make a minimal live call to the provider to verify its stored credentials
	and endpoint. Backs the "Test Connection" button on the AI Provider Credentials form.

	Reading an AI Provider Credentials (and decrypting its key) is restricted to System
	Manager, so we load the doc with permission checks and confirm read access
	before doing anything sensitive.
	"""
	provider = frappe.get_doc("AI Provider Credentials", provider_name)
	provider.check_permission("read")

	if not provider.enabled:
		return {
			"ok": False,
			"error_code": "PROVIDER_DISABLED",
			"message": _("This AI Provider Credentials is disabled. Enable it before testing."),
		}

	from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext
	from one_bpmn.agents.executor.direct_api import DirectApiExecutor

	# WI-001655: credentials carry no default model — test with any catalog
	# model linked to this record.
	test_model = frappe.db.get_value("AI Model", {"ai_provider_credentials": provider_name}, "name")
	if not test_model:
		return {
			"ok": False,
			"error_code": "NO_MODEL_LINKED",
			"message": _(
				"No AI Model in the catalog links these credentials. "
				"Create/link an AI Model record first, then test."
			),
		}
	config = ExecutorConfig(
		backend="direct_api",
		provider_name=provider_name,
		model=test_model,
		system_prompt="",
		user_prompt="ping",
		max_tokens=5,
		timeout_seconds=15,
		max_retries=0,
	)
	result = DirectApiExecutor().run(config, ExecutorContext())

	if result.error_code == ErrorCode.SUCCESS:
		return {
			"ok": True,
			"message": _("Connection successful."),
			"model": config.model or _("(provider default)"),
		}

	return {
		"ok": False,
		"error_code": result.error_code.value,
		"message": result.error_message or result.error_code.value,
	}
