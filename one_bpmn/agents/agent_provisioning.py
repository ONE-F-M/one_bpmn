# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Agent provisioning helpers (WI-001621, WI-001620).

The agent-creation process calls these to carry an AI Agent Configuration
from Draft to Live. Each is a plain callable so the BPMN service tasks stay
thin and the same checks can run outside the process (e.g. a doctype
sanity check before go-live).
"""

import frappe
from frappe import _


class AgentValidationError(frappe.ValidationError):
	pass


def validate_agent_config(config_name: str, test_provider: bool = True) -> dict:
	"""Validate the six essentials of a chat agent configuration (WI-001621).

	Checks, in order: identity, system prompt, LLM credentials link, and —
	for chat agents — a chat mode label; lints the prompt for unresolved
	template markers; and (optionally) makes a live provider test call so a
	bad key or model is caught before provisioning rather than at first use.

	Returns {"ok": bool, "errors": [...], "warnings": [...]}; never raises,
	so the process can route a failure to Needs Attention.
	"""
	errors, warnings = [], []
	cfg = frappe.get_doc("AI Agent Configuration", config_name)

	# 1. Identity
	if not cfg.agent_id:
		errors.append(_("Agent ID is required."))

	# 2. System prompt
	if not (cfg.system_prompt or "").strip():
		errors.append(_("System prompt is empty."))
	elif "{{" in cfg.system_prompt and "}}" in cfg.system_prompt:
		warnings.append(_("System prompt contains unresolved '{{ }}' markers."))

	# 3. LLM credentials
	if not cfg.ai_provider_credentials:
		errors.append(_("No AI Provider Credentials record is linked."))
	elif not frappe.db.get_value("AI Provider Credentials", cfg.ai_provider_credentials, "enabled"):
		errors.append(_("The linked AI Provider Credentials record is disabled."))

	# 4. Chat-type essentials
	if cfg.agent_type == "Chat" and not cfg.chat_mode_label:
		errors.append(_("Chat agents need a chat mode label."))

	# 5. Live provider test call
	if test_provider and cfg.ai_provider_credentials and not errors:
		ok, detail = _provider_test_call(cfg)
		if not ok:
			errors.append(_("Provider test call failed: {0}").format(detail))

	return {"ok": not errors, "errors": errors, "warnings": warnings}


def _provider_test_call(cfg) -> tuple[bool, str]:
	"""Make a minimal live call through the agent's resolved adapter."""
	try:
		from one_bpmn.agents.executor.direct_api import _run_coro_blocking
		from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
		from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

		adapter = get_llm_adapter_from_settings(get_agent_config(cfg.agent_id))
		completion = _run_coro_blocking(
			adapter.complete(system="Reply with the single word: OK.", user="ping", max_tokens=16)
		)
		text = getattr(completion, "text", str(completion or ""))
		return (bool(text and text.strip()), text.strip()[:80] or "empty response")
	except Exception as exc:
		return (False, str(exc)[:200])
