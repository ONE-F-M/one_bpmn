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


def allowed_roles_for(config_name: str) -> set:
	"""The roles allowed to use an agent. Empty means everyone.

	Empty-means-everyone is the EXISTING contract, not a new choice: every Live
	agent on the platform currently leaves the table empty, so reading empty as
	"nobody" would take the whole fleet offline the moment this is enforced.
	Restricting an agent is an opt-in act.
	"""
	try:
		return set(
			frappe.get_all(
				"AI Agent Allowed Role",
				filters={"parent": config_name, "parenttype": "AI Agent Configuration"},
				pluck="role",
			)
		)
	except Exception:
		# Unreadable table: fall back to unrestricted rather than locking every
		# user out of every agent on a transient read failure.
		#
		# The log write is wrapped separately because it can fail for the very
		# reason the read did — a database that cannot answer a query cannot
		# record that it could not answer a query, and an exception raised in
		# here would turn a degraded read into a hard failure for the user.
		try:
			frappe.log_error(
				title=f"Could not read allowed roles for {config_name} — treated as unrestricted",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return set()


def user_may_use_agent(config_name: str, user: str = None) -> bool:
	"""Whether ``user`` may invoke the agent named ``config_name``.

	THE ONE definition, deliberately. Before this existed, the chat picker
	filtered on allowed_roles and the invocation endpoint did not — so the field
	decided what a user was OFFERED while placing no limit on what they could
	CALL, and naming an agent directly walked straight past it. Two readings of
	one rule is how that happens, so both callers now go through here.

	System Manager is always allowed: it can edit the agent's roles anyway, so
	refusing it would be appearance rather than control.
	"""
	user = user or frappe.session.user
	allowed = allowed_roles_for(config_name)
	if not allowed:
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles & allowed) or "System Manager" in roles


def _authorize(config: dict, conversation_name: str = None):
	"""Decide whether this user may run this agent at all.

	Two gates, and every agent passes through one of them:

	- **Not yet Live** — its author or a System Manager only, so an agent can be
	  exercised before go-live without being reachable by end users.
	- **Live** — the agent's allowed_roles, enforced HERE and not merely in the
	  picker (WI-001840). ``invoke_agent`` is whitelisted, so anything reachable
	  from a browser can name an agent_id directly; a filter applied only to the
	  dropdown decided what was offered and stopped nothing.
	"""
	user = frappe.session.user
	lifecycle = config.get("lifecycle_status") or "Draft"
	config_name = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": config["agent_id"]}, ["name", "owner"], as_dict=True
	) or frappe._dict()

	if lifecycle == "Live":
		if config_name.name and not user_may_use_agent(config_name.name, user):
			frappe.throw(
				_("You do not have a role that is allowed to use the '{0}' agent.").format(
					config.get("chat_mode_label") or config["agent_id"]
				),
				frappe.PermissionError,
			)
		return

	if "System Manager" in frappe.get_roles(user):
		return
	if user != config_name.owner:
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
		# Same rule the invocation gate applies, read from the same function —
		# a picker that shows what cannot be called, or hides what can, is worse
		# than no filter at all.
		if not user_may_use_agent(cfg.name):
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

	# ── Rate limit + conversation freeze (WI-001968) ─────────────────────
	# Before any screening or model work: a refused turn should cost nothing,
	# and a frozen conversation must not reach the provider at all. Raises
	# RateLimited (a ValidationError) which surfaces to the caller as the
	# refusal message; everything else in here fails open.
	from one_bpmn.security import rate_limit as _rate_limit
	from one_bpmn.security.pii import _config_name

	# A Chat agent's turn is counted when its Chat Message is written, which is
	# the boundary that fires on EVERY message; counting here as well would make
	# one message cost two. Agents that never write a Chat Message are counted
	# here instead, or they would never be throttled at all.
	_rate_limit.enforce(
		user=frappe.session.user,
		agent=_config_name(config),
		agent_label=config.get("agent_id") or agent_id,
		conversation=conversation,
		count=(config.get("agent_type") != "Chat"),
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

	# ── Injection screening (WI-001967 detect, WI-001840 act) ────────────
	# Hooked here rather than on Chat Message so it runs exactly once per turn,
	# with the agent and conversation to hand. What a match DOES is the agent's
	# own setting: Log passes through, Flag removes the matched phrase and lets
	# the rest of the request stand, Block refuses the turn.
	#
	# Runs AFTER PII redaction on purpose. The rules match on instruction-shaped
	# phrasing, not on personal data, so they are unaffected by tokenisation —
	# while screening first would put the raw Civil ID into the security event's
	# hash input and undo the point of redacting it.
	#
	# Only a Block raises, and it raises an AgentRefusal so the caller reports
	# it as a decision. Every other failure path leaves the turn untouched.
	from one_bpmn.security.injection import screen_input as _screen_injection

	_injection = _screen_injection(
		message,
		config,
		boundary="input",
		conversation=conversation,
	)
	message = _injection.text

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

	# Output screening, before send. The Chat Message hook covers what is
	# PERSISTED; this covers what is RETURNED, and the two are not the same
	# thing — a direct-path agent answers without ever writing a Bot message,
	# and a blocked response must not reach the caller even when the transcript
	# already holds the redacted version.
	try:
		from one_bpmn.security.output_screening import screen_output

		screened = screen_output(result.get("response") or "", config, conversation=conversation)
		if screened.changed:
			result["response"] = screened.text
			result["output_screened"] = screened.summary()
			result["output_blocked"] = screened.blocked
	except Exception:
		frappe.log_error(
			title="Output screening skipped — response returned unchanged",
			message=frappe.get_traceback(),
		)

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
	"""Converted agents: the linked process map owns the whole turn.

	Resume re-arm (WI-001672 "confirm during build", confirmed broken): the
	insert hook spawns an instance for a NEW conversation, but a resumed
	conversation's instance has Completed with the map's close branch — so
	the first turn after a resume used to dead-end on "reopen the chat".
	When no live instance answers, re-arm through the SAME conditional-start
	gate the insert hook uses (_maybe_start_instance evaluates the map's own
	start condition and dedups), then retry the turn once.
	"""
	import time

	from one_bpmn.api.server_script_api import delegate_chat_turn

	result = delegate_chat_turn(conversation, message, context=context)

	# First-turn race (diagnosed live, 2026-08-08): the insert hook spawns the
	# instance and enqueues its first engine pass on the worker; a fast first
	# message can catch it Queued mid-start — the inline starter loses the
	# row-lock race and reads a not-yet-Active status one beat before the
	# worker commits. The production Lumina page solved this with a
	# wait-then-stream loop; same idea here, bounded: the SSE connection is
	# already streaming, so a few seconds of settling costs nothing visible.
	if result is None:
		# NB: not `for _ in range(...)` — that would shadow gettext's _ and
		# turn the throw below into `int(...)`.
		for _attempt in range(8):
			time.sleep(0.75)
			result = delegate_chat_turn(conversation, message, context=context)
			if result is not None:
				break

	if result is None and config.get("process_model"):
		try:
			from one_bpmn.one_bpmn.trigger import _maybe_start_instance

			_maybe_start_instance(
				frappe.get_doc("Chat Conversation", conversation), config["process_model"]
			)
			result = delegate_chat_turn(conversation, message, context=context)
		except Exception:
			frappe.log_error(
				title="bpmn_map resume re-arm failed", message=frappe.get_traceback()
			)
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
