# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Generic agent invocation (WI-001539).

One entry point for every configured agent, regardless of how the call
arrives — Desk chat, a Processa panel, a background trigger, or a future
API/MCP client. ``invoke_agent`` resolves the AI Agent Configuration and
dispatches to the runner matching how that agent executes today. Every
exchange is persisted to Chat Conversation / Chat Message.

The end state is a single execution engine (the agent's BPMN map); the
runner registry is the transitional seam that lets the not-yet-converted
agents keep working behind the same contract while each is migrated.
"""

import frappe
from frappe import _

from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config


def _runner_for(config: dict) -> str:
	"""Pick the runner key for an agent configuration.

	A linked process_model means the map drives it (the converted path).
	Otherwise fall back to the legacy runner recorded on the config's
	agent_framework, so unconverted agents keep working.
	"""
	if config.get("process_model"):
		return "bpmn_map"
	framework = (config.get("agent_framework") or "").strip().lower()
	# "anthropic" has no legacy runner left: every Anthropic-framework agent
	# (Docu, Logix, ProsAlly, LuCrusher) is map-driven and takes the branch
	# above, so a config claiming Anthropic without a map is a misconfiguration
	# and falls through to the single-shot path rather than a dead import.
	return {
		"google adk": "adk_stage_agent",
		"langgraph": "langgraph",
		"direct api": "direct_api",
	}.get(framework, "direct_api")


def _resolve_config(agent_id: str) -> dict:
	config = get_agent_config(agent_id)
	if not config:
		frappe.throw(_("No enabled AI Agent Configuration for agent '{0}'.").format(agent_id))
	return config


def _authorize(config: dict, conversation_name: str = None):
	"""A Draft (non-Live) agent is invocable only by its author/owner or a
	System Manager — for validation before go-live — and never surfaces to
	end users. Live agents are gated by allowed_roles elsewhere (WI-001618)."""
	lifecycle = config.get("lifecycle_status") or "Draft"
	if lifecycle == "Live":
		return
	user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return
	owner = frappe.db.get_value("AI Agent Configuration", {"agent_id": config["agent_id"]}, "owner")
	if user != owner:
		frappe.throw(
			_("Agent '{0}' is not yet Live and can only be exercised by its author.").format(config["agent_id"]),
			frappe.PermissionError,
		)


@frappe.whitelist()
def list_available_agents(include_legacy: int = 1) -> list:
	"""Return the chat agents the current user may use (WI-001618).

	The list is a query over enabled, Live, Chat-type AI Agent
	Configurations, filtered by each agent's allowed_roles (empty = all
	logged-in users). During the transition — until the legacy Lumina-page
	agents (General Chat, BA Agent) are migrated to Live configs — the
	hardcoded set is unioned in so the chat dropdown never empties. LuCrusher
	left that set in WI-001634: it is a Live, map-driven config now and is
	listed from the query like every other migrated agent.
	Each entry: {value (chat mode label), label, icon, agent_id}.
	"""
	user_roles = set(frappe.get_roles(frappe.session.user))
	agents, seen = [], set()

	configs = frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1, "agent_type": "Chat", "lifecycle_status": "Live"},
		fields=["name", "agent_id", "chat_mode_label", "icon", "process_model"],
	)
	for cfg in configs:
		if not cfg.chat_mode_label:
			continue
		# WI-001652: Live makes an agent referenceable in the editor; a
		# deployed linked diagram is what makes it CHATTABLE. Task-only agents
		# (no diagram, or diagram not deployed) stay out of the chat picker.
		if not cfg.process_model or not frappe.db.get_value(
			"BPMN Process Model", cfg.process_model, "is_active"
		):
			continue
		allowed = frappe.get_all(
			"AI Agent Allowed Role",
			filters={"parent": cfg.name, "parenttype": "AI Agent Configuration"},
			pluck="role",
		)
		if allowed and not (user_roles & set(allowed)):
			continue
		agents.append({
			"value": cfg.chat_mode_label,
			"label": cfg.chat_mode_label,
			"icon": cfg.icon or "🤖",
			"agent_id": cfg.agent_id,
		})
		seen.add(cfg.chat_mode_label)

	if int(include_legacy or 0):
		for label, icon in (("General Chat", "💬"), ("BA Agent", "📋")):
			if label not in seen:
				agents.append({"value": label, "label": label, "icon": icon, "agent_id": None, "legacy": True})

	return agents


@frappe.whitelist()
def invoke_agent(agent_id: str, message: str, conversation: str = None, context: dict = None):
	"""Invoke a configured agent with a single message; return its reply.

	Args:
	    agent_id: AI Agent Configuration.agent_id to run.
	    message: the user's input for this turn.
	    conversation: existing Chat Conversation to continue; a new one is
	        created (stamped with the agent's chat mode label) when omitted.
	    context: optional dict merged into the turn payload (editor state, etc.).

	Returns:
	    dict with at least ``response`` (the agent's reply text) and
	    ``conversation`` (the conversation name), plus runner-specific extras.
	"""
	if isinstance(context, str):
		context = frappe.parse_json(context)
	config = _resolve_config(agent_id)
	_authorize(config, conversation)

	# ── Rate limit + conversation freeze (WI-001968) ─────────────────────
	# Before any screening or model work: a refused turn should cost nothing,
	# and a frozen conversation must not reach the provider at all. Raises
	# RateLimited (a ValidationError) which surfaces to the caller as the
	# refusal message; everything else in here fails open.
	from one_bpmn.security import rate_limit as _rate_limit
	from one_bpmn.security.pii import _config_name

	_rate_limit.enforce(
		user=frappe.session.user,
		agent=_config_name(config),
		agent_label=config.get("agent_id") or agent_id,
		conversation=conversation,
	)

	# ── PII input screening (WI-001644) ──────────────────────────────────
	# Every agent invocation passes through here, so this is the one place
	# that can guarantee no user-supplied PII reaches a third-party model.
	# Detected values become stable tokens; the mapping lives for this turn
	# only and is swapped back at the tool boundary so lookups still resolve.
	from one_bpmn.security import pii as _pii
	from one_bpmn.security import turn as _turn

	# WI-001967: one id for everything this turn records. The security event is
	# written before the AI Agent Run exists and can never be edited afterwards,
	# so both are stamped with this instead of linked to each other.
	_turn.begin_turn()

	screened = _pii.screen_input(message, config)
	message = screened.text
	_pii_turn = _pii.begin_turn(screened, enabled=screened.enabled)

	# ── Injection screening (WI-001967) ──────────────────────────────────
	# Record-only: every rule in the pack that matches becomes an AI Security
	# Event, but nothing is altered and nothing is stopped — choosing what a
	# match should DO is 15.1. Hooked here rather than on Chat Message so it
	# runs exactly once per turn, with the agent and conversation to hand.
	# Never raises; a failure leaves the turn untouched.
	from one_bpmn.security.injection import screen_for_injection

	screen_for_injection(
		message,
		boundary="input",
		agent_configuration=_pii._config_name(config),
		conversation=conversation,
	)

	if not conversation:
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		conversation = create_agent_conversation(
			agent_id, title=(message or "New chat")[:140], user=frappe.session.user
		)

	runner = _runner_for(config)
	try:
		result = _RUNNERS[runner](config, conversation, message, context or {})
	finally:
		_pii.end_turn(_pii_turn)
		# Clear the correlation id too, or a pooled worker leaks it into the
		# next turn and two unrelated turns look like one.
		_turn.end_turn()
	if not isinstance(result, dict):
		result = {"response": str(result or "")}
	result.setdefault("conversation", conversation)
	result.setdefault("agent_id", agent_id)
	return result


# ── Runners ──────────────────────────────────────────────────────────────────
# Each takes (config, conversation_name, message, context) and returns a dict
# with a "response" key. They wrap today's execution styles behind one contract.


def _run_bpmn_map(config, conversation, message, context):
	"""Converted agents: the linked process map owns the whole turn."""
	from one_bpmn.api.server_script_api import delegate_chat_turn

	result = delegate_chat_turn(conversation, message, context=context)
	if result is None:
		frappe.throw(
			_("The process for agent '{0}' is not running for this conversation. Please reopen the chat.").format(
				config["agent_id"]
			)
		)
	return result


def _run_adk_stage_agent(config, conversation, message, context):
	"""ProsAlly / Logix / Docu today. Until their maps drive them (their own
	migration stories), prefer an already-running instance if one exists,
	else surface a clear message rather than silently forking execution."""
	from one_bpmn.api.server_script_api import delegate_chat_turn

	result = delegate_chat_turn(conversation, message, context=context)
	if result is not None:
		return result
	frappe.throw(
		_("Agent '{0}' has no running process for this conversation yet.").format(config["agent_id"])
	)


def _run_langgraph(config, conversation, message, context):
	"""BA Agent. Its graph runner lives in onefm_mcp; call through when present."""
	try:
		from onefm_mcp.onefm_mcp.page.lumina.lumina import send_message_with_agent
	except Exception:
		frappe.throw(_("The LangGraph runner for '{0}' is unavailable.").format(config["agent_id"]))
	resp = send_message_with_agent(conversation, message, stream=False)
	return resp if isinstance(resp, dict) else {"response": str(resp or "")}


def _run_direct_api(config, conversation, message, context):
	"""Single-shot / general chat. Persists the turn and calls the adapter's
	own (async) tool-calling loop for one exchange."""
	from one_bpmn.agents.executor.direct_api import _run_coro_blocking
	from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
	from one_bpmn.utils.chat_persistence import save_bot_message, save_user_message

	save_user_message(conversation, message)
	adapter = get_llm_adapter_from_settings(config)
	system_prompt = config.get("system_prompt") or ""
	completion = _run_coro_blocking(adapter.complete(system=system_prompt, user=message))
	text = getattr(completion, "text", str(completion or ""))
	save_bot_message(conversation, text)
	return {"response": text}


_RUNNERS = {
	"bpmn_map": _run_bpmn_map,
	"adk_stage_agent": _run_adk_stage_agent,
	"langgraph": _run_langgraph,
	"direct_api": _run_direct_api,
}
