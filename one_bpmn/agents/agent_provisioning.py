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


def _set_status(config_name: str, status: str):
	frappe.db.set_value("AI Agent Configuration", config_name, "lifecycle_status", status, update_modified=False)
	frappe.db.commit()


def provision_agent(config_name: str):
	"""v1 AI Agent creation process (WI-001620).

	Carries a chat agent from Draft to Live: Validating -> Provisioning
	(clone the chat-map template + compile/deploy so its start trigger arms)
	-> Live. Any failure lands the agent in Needs Attention with the reason
	logged; editing the configuration re-triggers this. Idempotent and safe
	to enqueue.
	"""
	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	if cfg.agent_type != "Chat":
		return  # background agents are provisioned by their own path (later pass)

	try:
		_set_status(config_name, "Validating")
		result = validate_agent_config(config_name)
		if not result["ok"]:
			_set_status(config_name, "Needs Attention")
			frappe.log_error(
				title=f"Agent provisioning: validation failed ({cfg.agent_id})",
				message="\n".join(result["errors"]),
			)
			return

		_set_status(config_name, "Provisioning")
		from one_bpmn.agents.chat_map_template import clone_chat_map_for_agent
		from one_bpmn.api.compilation import compile_process_model

		model_name = clone_chat_map_for_agent(config_name)
		compile_process_model(model_name)  # arms the conditional start trigger

		_set_status(config_name, "Live")
	except Exception:
		_set_status(config_name, "Needs Attention")
		frappe.log_error(
			title=f"Agent provisioning failed ({cfg.agent_id})",
			message=frappe.get_traceback(),
		)


def needs_generated_prompt(config_name: str) -> bool:
	"""Gateway predicate (WI-001620): does this agent still need a system
	prompt drafted for it? True when the prompt is blank."""
	return not (frappe.db.get_value("AI Agent Configuration", config_name, "system_prompt") or "").strip()


def generate_system_prompt(config_name: str) -> str:
	"""Draft a system prompt for an agent from its name + description, using
	its own linked credentials, and save it on the configuration (WI-001620).

	Body of the creation process's auto-prompt branch: when an agent is
	created without a prompt, the process generates one here rather than
	failing validation.
	"""
	from one_bpmn.agents.executor.direct_api import _run_coro_blocking
	from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
	from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	meta_prompt = (
		"You are an expert prompt engineer. Write a concise, production-ready "
		"system prompt for an AI chat agent with the following purpose. Return "
		"ONLY the system prompt text, no preamble or quotes.\n\n"
		f"Agent name: {cfg.agent_name}\n"
		f"Description: {cfg.description or '(none given)'}\n"
		f"Chat mode: {cfg.chat_mode_label or cfg.agent_id}"
	)
	adapter = get_llm_adapter_from_settings(get_agent_config(cfg.agent_id))
	completion = _run_coro_blocking(
		adapter.complete(system="You write system prompts.", user=meta_prompt, max_tokens=1024)
	)
	prompt = (getattr(completion, "text", "") or "").strip()
	if prompt:
		cfg.db_set("system_prompt", prompt, update_modified=False)
		frappe.cache.delete_value(f"agent_config:{cfg.agent_id}")
	return prompt


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
