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
def invoke_agent(
	agent_id: str, message: str, conversation: str = None, context: dict = None, stream: bool = False
):
	"""Invoke a configured agent with a single message; return its reply.

	Args:
	    agent_id: AI Agent Configuration.agent_id to run.
	    message: the user's input for this turn.
	    conversation: existing Chat Conversation to continue; a new one is
	        created (stamped with the agent's chat mode label) when omitted.
	    context: optional dict merged into the turn payload (editor state, etc.).
	    stream: internal callers only (the AG-UI endpoint, WI-001670). When
	        true, a runner that can stream returns its event generator instead
	        of a buffered reply; runners that cannot stream ignore the flag.

	Returns:
	    dict with at least ``response`` (the agent's reply text) and
	    ``conversation`` (the conversation name), plus runner-specific extras.
	    With ``stream=True`` and a streaming-capable runner, the dict instead
	    carries ``streaming=True`` and ``stream`` (the event generator) — a
	    shape that cannot ride a JSON response, hence the HTTP guard below.
	"""
	from frappe.utils import sbool

	stream = bool(sbool(stream))
	if stream and getattr(frappe.local, "request", None) is not None:
		cmd = (frappe.form_dict or {}).get("cmd") or ""
		if cmd.endswith("invoke_agent"):
			frappe.throw(
				_(
					"stream=True cannot be requested over HTTP on this method — use "
					"one_bpmn.api.agui.stream_agent_turn, which speaks Server-Sent Events."
				)
			)
	if isinstance(context, str):
		context = frappe.parse_json(context)
	config = _resolve_config(agent_id)
	_authorize(config, conversation)

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
	result = None
	try:
		result = _RUNNERS[runner](config, conversation, message, context or {}, stream=stream)
	finally:
		# Streaming replies are consumed after this function returns, so the
		# PII turn must survive until the generator is exhausted — the wrapper
		# below owns the teardown in that case.
		if not _is_stream(result):
			_pii.end_turn(_pii_turn)
		# Clear the correlation id too, or a pooled worker leaks it into the
		# next turn and two unrelated turns look like one.
		_turn.end_turn()
	if _is_stream(result):
		return {
			"streaming": True,
			"stream": _stream_with_pii_teardown(result, _pii_turn),
			"conversation": conversation,
			"agent_id": agent_id,
		}
	if not isinstance(result, dict):
		result = {"response": str(result or "")}
	result.setdefault("conversation", conversation)
	result.setdefault("agent_id", agent_id)
	return result


def _is_stream(value) -> bool:
	"""True for the iterator shapes a streaming runner may hand back."""
	import inspect

	return inspect.isgenerator(value) or (hasattr(value, "__next__") and not isinstance(value, dict))


def _stream_with_pii_teardown(gen, pii_turn):
	"""Relay a runner's event stream, ending the PII turn only once the
	stream is exhausted (or abandoned) — mirrors the try/finally the buffered
	path gets inline."""
	from one_bpmn.security import pii as _pii

	try:
		yield from gen
	finally:
		_pii.end_turn(pii_turn)


# ── Runners ──────────────────────────────────────────────────────────────────
# Each takes (config, conversation_name, message, context, stream=False) and
# returns a dict with a "response" key. A runner that can stream may instead
# return an event generator when stream=True; runners that cannot simply
# ignore the flag (WI-001670). They wrap today's execution styles behind one
# contract.


def _run_bpmn_map(config, conversation, message, context, stream=False):
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


def _run_adk_stage_agent(config, conversation, message, context, stream=False):
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


def _run_langgraph(config, conversation, message, context, stream=False):
	"""BA Agent. Its graph runner lives in onefm_mcp; call through when present.

	WI-001670: the ``stream`` flag now passes through instead of being forced
	to False. That hard-coded False made this runner unable to run the BA
	agent at all — ``send_message_with_agent`` throws "BA Agent only supports
	streaming mode" on non-streaming calls. With stream=True the runner hands
	back the agent's event generator for the shared AG-UI stream to relay."""
	try:
		from onefm_mcp.onefm_mcp.page.lumina.lumina import send_message_with_agent
	except Exception:
		frappe.throw(_("The LangGraph runner for '{0}' is unavailable.").format(config["agent_id"]))
	resp = send_message_with_agent(conversation, message, stream=stream)
	if _is_stream(resp):
		return resp
	return resp if isinstance(resp, dict) else {"response": str(resp or "")}


def _run_direct_api(config, conversation, message, context, stream=False):
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


@frappe.whitelist()
def get_agent_surface(agent_id: str) -> dict:
	"""Everything the shared AgentChatPanel needs to draw an agent's chat
	surface, read from AI Agent Configuration (WI-001996) — greeting,
	composer placeholder, surface classification, starter prompts, label and
	icon. No agent-specific strings live in components.

	Enforces the same allowed_roles gate as invoking the agent.
	"""
	config = _resolve_config(agent_id)
	_authorize(config, None)

	name = config.get("name") or frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": agent_id, "enabled": 1}
	)
	row = (
		frappe.db.get_value(
			"AI Agent Configuration",
			name,
			[
				"agent_name",
				"chat_mode_label",
				"icon",
				"chat_description",
				"greeting",
				"composer_placeholder",
				"surface_type",
				"artifact_type",
			],
			as_dict=True,
		)
		or {}
	)
	sample_prompts = frappe.get_all(
		"AI Agent Sample Prompt",
		filters={"parenttype": "AI Agent Configuration", "parent": name},
		pluck="prompt",
		order_by="idx asc",
		limit=6,
	)
	return {
		"agent_id": agent_id,
		"label": row.get("chat_mode_label") or row.get("agent_name") or agent_id,
		"icon": row.get("icon") or "",
		"description": row.get("chat_description") or "",
		"greeting": row.get("greeting") or "",
		"composer_placeholder": row.get("composer_placeholder") or "",
		"surface_type": row.get("surface_type") or "Conversation",
		"artifact_type": row.get("artifact_type") or "None",
		"sample_prompts": sample_prompts,
	}
