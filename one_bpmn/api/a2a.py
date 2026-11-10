# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A protocol door (agent card, JSON-RPC, push callback) and invoke_agent, the one entry point for every configured agent.

Card discovery is guest-readable and answers a hidden agent with the same 404 as a missing one.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from one_bpmn.a2a import execute, protocol, push, task_store
from one_bpmn.a2a.card import build_agent_card
from one_bpmn.a2a.principal import client_may_invoke, get_client_for_user
from one_bpmn.a2a.protocol import A2AError
from one_bpmn.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config


@frappe.whitelist(allow_guest=True, methods=["GET"])
def agent_card(agent_id: str) -> dict:
	"""The public Agent Card for one exposed agent."""
	card = build_agent_card(agent_id)
	if card is None:
		raise frappe.DoesNotExistError
	return card


# ── Push callback: a remote telling us a delegated task moved ─────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
def push_callback() -> dict:
	"""A remote agent reports that a task we delegated has changed.

	Reachable without a Frappe session — the remote has no user here — so
	the per-task token IS the gate. Every failure returns the same opaque
	answer: a caller must not be able to use this endpoint to learn which
	task ids exist. Nothing here trusts the body beyond the state field;
	the payload is a claim, and the row is the record.

	Idempotent and forward-only: a replayed or late callback for a task that
	already reached a terminal state changes nothing.
	"""
	from one_bpmn.a2a.contract import terminal_states
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume
	from one_bpmn.processa_engine.runtime.remote_waits import on_a2a_input_required
	from one_bpmn.a2a import client as a2a_client

	opaque = {"accepted": False}
	if push.callback_throttled():
		return opaque
	try:
		payload = json.loads(frappe.request.data or b"{}")
	except Exception:
		return opaque
	if not isinstance(payload, dict):
		return opaque

	remote_task_id = payload.get("id") or payload.get("taskId")
	presented = (frappe.get_request_header(push.TOKEN_HEADER) or "").strip()
	if not remote_task_id:
		return opaque

	name = frappe.db.get_value(
		"A2A Task",
		{"direction": "Outbound", "remote_task_id": remote_task_id, "push_registered": 1},
		"name",
	)
	if not name:
		return opaque

	task = frappe.get_doc("A2A Task", name)
	if not push.token_matches(task, presented):
		# Deliberately indistinguishable from "no such task".
		frappe.log_error(
			title="A2A push callback rejected — token mismatch",
			message=f"task={task.name} remote_task_id={remote_task_id}",
		)
		return opaque

	if task.state in terminal_states():
		return {"accepted": True}  # already settled — replay is a no-op

	state = a2a_client.remote_state(payload) or "working"
	text = a2a_client.remote_text(payload)

	if state == "completed":
		task.db_set(
			{
				"state": "completed",
				"result": frappe.as_json({"text": text}),
				"status_message": text[:500],
				"completed_at": frappe.utils.now_datetime(),
			},
			update_modified=True,
		)
		enqueue_wait_resume(task.instance, task.wf_task_id, task.name, "A2A Task")
	elif state in ("failed", "canceled", "rejected"):
		task.db_set(
			{
				"state": state,
				"error_message": (text or state)[:500],
				"completed_at": frappe.utils.now_datetime(),
			},
			update_modified=True,
		)
		enqueue_wait_resume(task.instance, task.wf_task_id, task.name, "A2A Task")
	elif state == "input-required":
		task.db_set({"state": "input-required"}, update_modified=True)
		if task.instance:
			instance = frappe.get_doc("BPMN Process Instance", task.instance)
			on_a2a_input_required(instance, task.name, text)
	else:
		task.db_set({"state": state}, update_modified=True)

	return {"accepted": True}


# The JSON-RPC door


@frappe.whitelist(methods=["POST"])
def rpc(agent_id: str = None, **kwargs):
	"""The A2A task endpoint: message/send, tasks/get, tasks/cancel.

	Just another authenticated door into invoke_agent — not a separate
	runtime. The caller authenticates natively (its client user's API
	key); the gate then resolves the approved A2A Client row and checks
	the target agent is enabled + Live + exposed AND on that client's
	allowed list. Every response is HTTP 200 carrying a JSON-RPC result
	or error object.
	"""
	request_id = None
	try:
		envelope = protocol.parse_rpc_request()
		request_id = envelope.get("id")
		method = envelope.get("method")
		params = envelope.get("params") or {}

		client = get_client_for_user()
		if not client:
			raise A2AError("INVALID_REQUEST", "caller is not an approved A2A client")

		if method == "message/send":
			result = _message_send(client, agent_id, params)
		elif method == "tasks/get":
			result = _tasks_get(params)
		elif method == "tasks/cancel":
			result = _tasks_cancel(params)
		elif method == "tasks/pushNotificationConfig/set":
			result = _set_push_config(params)
		else:
			raise A2AError("UNSUPPORTED_OPERATION", f"'{method}' is not supported by this agent")

		protocol.respond_result(request_id, result)
	except A2AError as error:
		protocol.respond_error(request_id, error.code, error.message, error.data)
	except Exception:
		frappe.log_error(title="A2A rpc failed", message=frappe.get_traceback())
		protocol.respond_error(
			request_id, protocol.a2a_contract.error_code("INTERNAL_ERROR"), "internal error"
		)


def _gate_agent(client: str, agent_id: str):
	"""Enabled + Live + exposed + on the caller's allowed list. Every
	failure is the same message — a caller must not be able to probe
	which agents exist."""
	refused = A2AError("INVALID_PARAMS", "agent not available to this caller")
	if not agent_id:
		raise refused
	config = frappe.db.get_value(
		"AI Agent Configuration",
		{"agent_id": agent_id},
		["name", "agent_id", "enabled", "lifecycle_status", "agent_type", "process_model", "a2a_exposed"],
		as_dict=True,
	)
	if not config or not (config.enabled and config.lifecycle_status == "Live" and config.a2a_exposed):
		raise refused
	if not client_may_invoke(client, config.name):
		raise refused
	return config


def _message_send(client: str, agent_id: str, params: dict) -> dict:
	message = protocol.validate_message_params(params)
	text = protocol.extract_text_parts(message)

	if message.get("taskId"):
		return _continue_task(message, text)

	config = _gate_agent(client, agent_id)
	trace = protocol.read_trace(message)
	task = task_store.create_inbound_task(config, client, message, text, trace)

	# A caller may ask to be told rather than poll, right in the send.
	caller_push = ((params or {}).get("configuration") or {}).get("pushNotificationConfig")
	if caller_push:
		push.store_caller_config(task, caller_push)

	# One implementation of "run this agent for this task", shared with the
	# same-site path in a2a/local.
	execute.run_for_task(task, config, text)

	task_store.refresh_state(task)
	return protocol.task_to_wire(task)


def _continue_task(message: dict, text: str) -> dict:
	"""The caller answers an input-required pause. This path bypasses
	invoke_agent, so screening is mirrored explicitly before the answer
	reaches the suspended run."""
	task = task_store.get_task_for_principal(message["taskId"])
	task_store.refresh_state(task)
	if task.state != "input-required":
		raise A2AError("INVALID_PARAMS", "task is not waiting for input")
	if not (task.instance and task.pending_human_task):
		raise A2AError("INTERNAL_ERROR", "task has no resumable pause")

	text = _screen_continuation(task, text)

	from one_bpmn.api.instances import complete_task

	complete_task(task.instance, task.pending_human_task, json.dumps({"response": text}))
	task.db_set(
		{"state": "working", "pending_human_task": "", "status_message": ""}, update_modified=True
	)
	task.reload()
	return protocol.task_to_wire(task)


def _screen_continuation(task, text: str) -> str:
	"""Mirror of invoke_agent's input screening chain for the one path
	that bypasses it: rate limit, turn correlation, PII, injection."""
	from one_bpmn.ai_agent_security import rate_limit as _rate_limit
	from one_bpmn.ai_agent_security import turn as _turn
	from one_bpmn.ai_agent_security.screening import pii as _pii
	from one_bpmn.ai_agent_security.screening.injection import screen_for_injection

	_rate_limit.enforce(
		user=frappe.session.user,
		agent=task.agent_configuration,
		agent_label=task.agent_configuration,
		conversation=task.conversation,
		count=True,
	)
	_turn.begin_turn()
	config = frappe.get_cached_doc("AI Agent Configuration", task.agent_configuration)
	screened = _pii.screen_input(text, config)
	screen_for_injection(
		screened.text,
		boundary="input",
		agent_configuration=task.agent_configuration,
		conversation=task.conversation,
	)
	return screened.text


def _tasks_get(params: dict) -> dict:
	task = task_store.get_task_for_principal((params or {}).get("id"))
	task_store.refresh_state(task)
	history = task_store.build_history(task, (params or {}).get("historyLength"))
	return protocol.task_to_wire(task, history=history)


def _set_push_config(params: dict) -> dict:
	"""A caller asks us to tell them when their task changes, instead of
	polling for it. Their URL is SSRF-checked because we will be calling it."""
	task = task_store.get_task_for_principal((params or {}).get("taskId"))
	config = (params or {}).get("pushNotificationConfig") or {}
	push.store_caller_config(task, config)
	return {
		"taskId": task.task_id,
		"pushNotificationConfig": {"url": task.push_callback_url},
	}


def _tasks_cancel(params: dict) -> dict:
	"""Cancelable only before real work: submitted or input-required. No
	engine kill path exists, so a working task cannot be stopped mid-pass."""
	task = task_store.get_task_for_principal((params or {}).get("id"))
	task_store.refresh_state(task)
	if task.state not in ("submitted", "input-required"):
		raise A2AError("TASK_NOT_CANCELABLE", f"task is {task.state}")

	locked = frappe.get_doc("A2A Task", task.name, for_update=True)
	if locked.state not in ("submitted", "input-required"):
		raise A2AError("TASK_NOT_CANCELABLE", f"task is {locked.state}")
	locked.db_set(
		{"state": "canceled", "completed_at": frappe.utils.now_datetime()}, update_modified=True
	)
	if locked.conversation:
		try:
			from one_bpmn.ai_agent_conversations.chat_persistence import close_conversation

			close_conversation(locked.conversation)
		except Exception:
			frappe.log_error(title="A2A cancel: close_conversation failed", message=frappe.get_traceback())
	locked.reload()
	return protocol.task_to_wire(locked)



def _runner_for(config: dict) -> str:
	"""Pick the runner key for an agent configuration.

	A linked process_model means the map drives it (the converted path).
	Otherwise fall back to the legacy runner recorded on the config's
	agent_framework, so unconverted agents keep working.
	"""
	if config.get("process_model"):
		return "bpmn_map"
	framework = (config.get("agent_framework") or "").strip().lower()
	# Neither "anthropic" nor "langgraph" has a legacy runner left: every agent
	# on either framework (Docu, Logix, ProsAlly, LuCrusher, and now the BA
	# Agent) is map-driven and takes the branch above, so a config claiming one
	# of them without a map is a misconfiguration and falls through to the
	# single-shot path rather than a dead import.
	return {
		"google adk": "adk_stage_agent",
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
	  picker. ``invoke_agent`` is whitelisted, so anything reachable
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
	"""Return the chat agents the current user may use.

	The list is a query over enabled, Live, Chat-type AI Agent
	Configurations, filtered by each agent's allowed_roles (empty = all
	logged-in users). During the transition — until the last legacy Lumina-page
	agent (General Chat) is migrated to a Live config — the
	hardcoded set is unioned in so the chat dropdown never empties. LuCrusher
	and the BA Agent have both left that set: they are Live, map-driven configs
	and are listed from the query like every other migrated agent, leaving
	General Chat as the last legacy entry.
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
		# Live makes an agent referenceable in the editor; a
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
		for label, icon in (("General Chat", "💬"),):
			if label not in seen:
				agents.append({"value": label, "label": label, "icon": icon, "agent_id": None, "legacy": True})

	return agents


# The ONE AI page is the Lumina page's successor, so it offers the Lumina
# page's own modes and nothing else — LUMINA_NATIVE_MODES in onefm_mcp's
# lumina.py, expressed here as agent ids. Order is the picker's order.
# ``ba_architect`` and not "ba_agent": the id here was a guess at what the BA
# Agent's configuration would be called, no such record ever existed, and the
# lookup below silently dropped the agent from the page. The record's real id is
# ``ba_architect`` — "BA Agent" is its chat_mode_label, which is the same
# label-versus-id trap LuCrusher hit.
ONE_AI_AGENT_IDS = ("lumina_general_chat", "ba_architect", "lucrusher_agent")
# Well inside the stream's stall ceiling, so a live turn's "still working" note always arrives first.
_STILL_WORKING_AFTER_SECONDS = 60


@frappe.whitelist()
def list_one_ai_agents() -> list:
	"""The fixed agent list for the ONE AI page.

	Every field the picker shows comes from the agent's own AI Agent
	Configuration, never from a copy kept here: LuCrusher's label is its map's
	start trigger, so a copy that spells it differently starts no instance.
	An agent that is missing, disabled or not Live on this site is not offered.

	Returns:
	    list of {value (chat mode label), label, icon, agent_id}, in
	    ONE_AI_AGENT_IDS order.
	"""
	user_roles = set(frappe.get_roles(frappe.session.user))
	agents = []

	for agent_id in ONE_AI_AGENT_IDS:
		cfg = frappe.db.get_value(
			"AI Agent Configuration",
			{"agent_id": agent_id, "enabled": 1, "agent_type": "Chat", "lifecycle_status": "Live"},
			["name", "agent_id", "chat_mode_label", "icon", "process_model"],
			as_dict=True,
		)
		if not cfg or not cfg.chat_mode_label:
			continue
		# The deployed-diagram gate applies only to map-driven agents: a mode
		# may still run on the direct-api runner, which needs no diagram at all
		# (see _runner_for).
		if cfg.process_model and not frappe.db.get_value(
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

	return agents


def one_ai_conversation_modes() -> list:
	"""agent_mode values that belong to the ONE AI page's own conversations.

	Conversations record either the chat label or the bare agent id, so both
	are returned. Used to keep other surfaces' chats (Logix, ProsAlly, Docu,
	every future agent) out of the page's history sidebar — the same rule
	Lumina applies with _registry_only_agent_modes.
	"""
	modes = list(ONE_AI_AGENT_IDS)
	labels = frappe.get_all(
		"AI Agent Configuration",
		filters={"agent_id": ["in", ONE_AI_AGENT_IDS]},
		pluck="chat_mode_label",
	)
	modes.extend(label for label in labels if label)
	return modes


@frappe.whitelist()
def invoke_agent(
	agent_id: str,
	message: str,
	conversation: str = None,
	context: dict = None,
	stream: bool = False,
	client_message_id: str = None,
):
	"""Invoke a configured agent with a single message; return its reply.

	Args:
	    agent_id: AI Agent Configuration.agent_id to run.
	    message: the user's input for this turn.
	    conversation: existing Chat Conversation to continue; a new one is
	        created (stamped with the agent's chat mode label) when omitted.
	    context: optional dict merged into the turn payload (editor state, etc.).
	    stream: internal callers only (the AG-UI endpoint). When
	        true, a runner that can stream returns its event generator instead
	        of a buffered reply; runners that cannot stream ignore the flag.
	    client_message_id: id minted by the chat client for this message. Sending
	        it twice returns the first reply instead of running the agent again,
	        so a retry or a double submit costs nothing and says nothing twice.

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

	# Some chat clients submit HTML-escaped text (e.g. a rich-text/
	# contenteditable input serializing its content before it reaches this
	# endpoint) even though ``message`` is meant to be plain text — observed
	# live as an escaped ``&lt;PROJECT&gt;``-style placeholder surviving all
	# the way into a durable AI Memory row. Decoding entities here, before
	# anything else touches the message, means every downstream consumer
	# (PII/injection screening, the rendered prompt, chat history, long-term
	# memory) sees the plain text. Entity-decoding only (not full
	# ``strip_html``): unlike markup tags, a plain chat message can
	# legitimately contain a literal ``<...>``-shaped placeholder, and this
	# must not corrupt that.
	from one_bpmn.ai_agent_memory.text_clean import unescape_entities

	message = unescape_entities(message)

	config = _resolve_config(agent_id)
	_authorize(config, conversation)

	# Rate limit and conversation freeze
	# Before any screening or model work: a refused turn should cost nothing,
	# and a frozen conversation must not reach the provider at all. Raises
	# RateLimited (a ValidationError) which surfaces to the caller as the
	# refusal message; everything else in here fails open.
	from one_bpmn.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import agent_config_name
	from one_bpmn.ai_agent_security import rate_limit as _rate_limit

	# A Chat agent's turn is counted when its Chat Message is written, which is
	# the boundary that fires on EVERY message; counting here as well would make
	# one message cost two. Agents that never write a Chat Message are counted
	# here instead, or they would never be throttled at all.
	_rate_limit.enforce(
		user=frappe.session.user,
		agent=agent_config_name(config),
		agent_label=config.get("agent_id") or agent_id,
		conversation=conversation,
		count=(config.get("agent_type") != "Chat"),
	)

	# Broken credentials
	# A model the platform already knows cannot answer is refused before the
	# turn starts: no Chat Message, no process instance, no failed run. The
	# reason is an AgentRefusal, so the chat surface shows it as a message
	# rather than "something went wrong".
	from one_bpmn.ai_agent_registry import model_health as _model_health

	_unavailable = _model_health.refuse_new_run(config.get("ai_model"), commit=True)
	if _unavailable:
		raise _model_health.ModelUnavailable(_unavailable)

	# PII input screening
	# Every agent invocation passes through here, so this is the one place
	# that can guarantee no user-supplied PII reaches a third-party model.
	# Detected values become stable tokens; the mapping lives for this turn
	# only and is swapped back at the tool boundary so lookups still resolve.
	from one_bpmn.ai_agent_security import turn as _turn
	from one_bpmn.ai_agent_security.screening import pii as _pii

	# One id for everything this turn records. The security event is
	# written before the AI Agent Run exists and can never be edited afterwards,
	# so both are stamped with this instead of linked to each other.
	_turn.begin_turn()

	screened = _pii.screen_input(message, config)
	message = screened.text
	_pii_turn = _pii.begin_turn(screened, enabled=screened.enabled)

	# ── Injection screening: detect, then act ────────────────────────────
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
	from one_bpmn.ai_agent_security.screening.injection import screen_input as _screen_injection

	_injection = _screen_injection(
		message,
		config,
		boundary="input",
		conversation=conversation,
	)
	message = _injection.text

	if not conversation:
		from one_bpmn.ai_agent_conversations.chat_persistence import create_agent_conversation

		conversation = create_agent_conversation(
			agent_id, title=(message or "New chat")[:140], user=frappe.session.user
		)

	# ── Same message twice ───────────────────────────────────────────────
	# Checked once the conversation is known and before the lock, so a
	# redelivery neither waits behind the turn it duplicates nor is refused by
	# it. Costs one indexed read on the common path.
	from one_bpmn.processa_engine.agent_runtime import turn_idempotency as _idem

	if client_message_id:
		_already = _idem.find_existing(conversation, client_message_id)
		if _already:
			_pii.end_turn(_pii_turn)
			_turn.end_turn()
			_already.setdefault("agent_id", agent_id)
			return _already

	# ── One turn at a time on this conversation ──────────────────────────
	# Two overlapping deliveries each restore the same workflow_state and the
	# last write wins, losing a turn's work and interleaving the transcript.
	# Whether a second message waits or is turned away is the agent's setting.
	from one_bpmn.ai_agent_security import turn_lock as _turn_lock

	_lock_token = None
	try:
		_lock_token = _turn_lock.acquire(conversation, _turn_lock.policy_for(config))
	except Exception:
		_pii.end_turn(_pii_turn)
		_turn.end_turn()
		raise

	# The map reuses a message we have already written instead of inserting its
	# own, which is how the client's id reaches the transcript.
	context = dict(context or {})
	_user_message = ""
	if client_message_id:
		try:
			_user_message = _idem.record_user_message(
				conversation, message, client_message_id, existing=context.get("message_name") or ""
			)
			context.setdefault("message_name", _user_message)
		except Exception:
			frappe.log_error(
				title="Chat message id not recorded — turn continues without it",
				message=frappe.get_traceback(),
			)

	runner = _runner_for(config)
	result = None
	try:
		result = _RUNNERS[runner](config, conversation, message, context, stream=stream)
	finally:
		# Streaming replies are consumed after this function returns, so the
		# PII turn must survive until the generator is exhausted — the wrapper
		# below owns the teardown in that case.
		if not _is_stream(result):
			_pii.end_turn(_pii_turn)
			_turn_lock.release(conversation, _lock_token)
		# Clear the correlation id too, or a pooled worker leaks it into the
		# next turn and two unrelated turns look like one.
		_turn.end_turn()
	if _is_stream(result):
		envelope = dict(result) if isinstance(result, dict) else {}
		inner = envelope.pop("stream", result)
		envelope.pop("streaming", None)
		return {
			**envelope,
			"streaming": True,
			# A streamed turn is still running when this returns, so the lock
			# has to outlive the function the same way the PII turn does.
			"stream": _stream_with_pii_teardown(
				inner, _pii_turn, conversation=conversation, lock_token=_lock_token
			),
			"conversation": conversation,
			"agent_id": agent_id,
		}
	if not isinstance(result, dict):
		result = {"response": str(result or "")}

	# Note which reply answered this message, so a redelivery of the same id is
	# served from the transcript instead of running the agent again.
	if _user_message and result.get("message_name"):
		_idem.record_reply(_user_message, result["message_name"])

	# Output screening, before send. The Chat Message hook covers what is
	# PERSISTED; this covers what is RETURNED, and the two are not the same
	# thing — a direct-path agent answers without ever writing a Bot message,
	# and a blocked response must not reach the caller even when the transcript
	# already holds the redacted version.
	try:
		from one_bpmn.ai_agent_security.screening.output_screening import screen_output

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
	"""True for the shapes a runner hands back when it is streaming.

	A runner may return the generator itself, or the ``{"streaming": True,
	"stream": <generator>}`` envelope _run_bpmn_map uses. Reading only the bare
	generator treated every map-driven chat turn as finished the moment the
	runner returned: the turn lock and the PII turn were torn down about eighty
	milliseconds in, while the map had not produced a token. One turn at a time
	stopped being one turn at a time, for every agent whose map drives it.
	"""
	import inspect

	if isinstance(value, dict):
		return bool(value.get("streaming")) and value.get("stream") is not None
	return inspect.isgenerator(value) or hasattr(value, "__next__")


def _stream_with_pii_teardown(gen, pii_turn, conversation=None, lock_token=None):
	"""Relay a runner's event stream, ending the PII turn and releasing the
	conversation's turn lock only once the stream is exhausted (or abandoned) —
	mirrors the try/finally the buffered path gets inline."""
	from one_bpmn.ai_agent_security import turn_lock as _turn_lock
	from one_bpmn.ai_agent_security.screening import pii as _pii

	try:
		yield from gen
	finally:
		_pii.end_turn(pii_turn)
		_turn_lock.release(conversation, lock_token)


# ── Runners ──────────────────────────────────────────────────────────────────
# Each takes (config, conversation_name, message, context, stream=False) and
# returns a dict with a "response" key. A runner that can stream may instead
# return an event generator when stream=True; runners that cannot simply
# ignore the flag. They wrap today's execution styles behind one
# contract.


def _rearm_and_deliver(config, conversation, message, context, wait: bool = True):
	"""Re-arm a conversation whose instance has closed, then deliver once more.

	A resumed conversation's instance has Completed with the map's close branch,
	so the first turn after a resume has nothing to deliver to. This goes
	through the same conditional-start gate the insert hook uses, which
	evaluates the map's own start condition and dedups.
	"""
	from one_bpmn.api.server_scripts import delegate_chat_turn

	if not config.get("process_model"):
		return None
	try:
		from one_bpmn.processa_engine.triggers import _maybe_start_instance

		_maybe_start_instance(
			frappe.get_doc("Chat Conversation", conversation), config["process_model"]
		)
		return delegate_chat_turn(conversation, message, context=context, wait=wait)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="bpmn_map resume re-arm failed", message=frappe.get_traceback())
		return None


def _no_live_instance(config, conversation):
	last = frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "Chat Conversation", "context_docname": conversation},
		fields=["name", "status", "waiting_for_ai", "waiting_for_human", "modified"],
		order_by="creation desc",
		limit=1,
	)
	from one_bpmn.processa_engine.agent_runtime import turn_signal

	if last and last[0].status == "Active" and turn_signal.ai_job_running(last[0].name):
		frappe.throw(
			_("I'm still working on your previous message. Wait for that reply, then send this one again.")
		)
	# Deferred so the entry survives the rollback that follows the throw.
	frappe.log_error(
		title=f"Chat turn found no waiting process ({config['agent_id']})",
		message=f"conversation: {conversation}\nlatest instance: {last[0] if last else 'none'}",
		reference_doctype="Chat Conversation",
		reference_name=conversation,
		defer_insert=True,
	)
	frappe.throw(
		_("The process for agent '{0}' is not running for this conversation. Please reopen the chat.").format(
			config["agent_id"]
		)
	)


def _bpmn_turn_stream(config, conversation, message, context):
	"""Deliver the turn, relay the worker's progress, hand over the reply.

	The turn runs on the bpmn_ai_agent worker, so the request is free to report
	what it is doing while it runs. Tools announce themselves from the shape
	runner; this relays those announcements and finishes with the reply, which
	the stream shapes the same way it shapes a runner that never streamed.
	"""
	from one_bpmn.processa_engine.agent_runtime import turn_signal
	from one_bpmn.ai_agent_conversations.agui.stream import HANDOVER_EVENT
	from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
	from one_bpmn.api.server_scripts import collect_chat_turn_reply, delegate_chat_turn
	from one_bpmn.processa_engine.dispatch.ai_agent import TURN_OUTPUT_EVENT

	handle = delegate_chat_turn(conversation, message, context=context, wait=False)
	if handle is None:
		handle = _rearm_and_deliver(config, conversation, message, context, wait=False)
	if handle is None:
		_no_live_instance(config, conversation)

	if not handle.get("pending"):
		# The reply was already there: an inline engine pass in tests, or a turn
		# the map answered without parking anything.
		yield {"type": HANDOVER_EVENT, "result": handle}
		return

	# The worker's job is queued to start after this request commits, so nothing
	# runs until the transaction is released. Progress would never arrive.
	if not frappe.flags.in_test:
		# nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		frappe.db.commit()

	# The task output is the answer, not a status line: it goes to the
	# collector, never to the client.
	task_output = {}
	# A quiet minute keeps waiting only while the turn's AI job lives, never past the job's own limit.
	for event in turn_signal.consume(
		handle["instance"],
		AI_AGENT_JOB_TIMEOUT + 60,
		idle_seconds=_STILL_WORKING_AFTER_SECONDS,
		still_running=lambda: turn_signal.ai_job_running(handle["instance"]),
	):
		if isinstance(event, dict) and event.get("type") == TURN_OUTPUT_EVENT:
			task_output["output"] = event.get("output")
			continue
		yield event

	result = collect_chat_turn_reply(handle, task_output.get("output"))
	if result is None:
		_no_live_instance(config, conversation)
	yield {"type": HANDOVER_EVENT, "result": result}


def _run_bpmn_map(config, conversation, message, context, stream=False):
	"""Converted agents: the linked process map owns the whole turn.

	Resume re-arm: the
	insert hook spawns an instance for a NEW conversation, but a resumed
	conversation's instance has Completed with the map's close branch — so
	the first turn after a resume used to dead-end on "reopen the chat".
	When no live instance answers, re-arm through the SAME conditional-start
	gate the insert hook uses (_maybe_start_instance evaluates the map's own
	start condition and dedups), then retry the turn once.
	"""
	from one_bpmn.api.server_scripts import delegate_chat_turn

	if stream:
		return {
			"streaming": True,
			"stream": _bpmn_turn_stream(config, conversation, message, context),
		}

	result = delegate_chat_turn(conversation, message, context=context)

	# Delivery already accepts a Queued instance and waits for the worker, so
	# nothing back means no live instance. Re-arm instead of retrying.

	if result is None:
		result = _rearm_and_deliver(config, conversation, message, context)
	if result is None:
		_no_live_instance(config, conversation)
	return result


def _run_adk_stage_agent(config, conversation, message, context, stream=False):
	"""ProsAlly / Logix / Docu today. Until their maps drive them (their own
	migration stories), prefer an already-running instance if one exists,
	else surface a clear message rather than silently forking execution."""
	from one_bpmn.api.server_scripts import delegate_chat_turn

	result = delegate_chat_turn(conversation, message, context=context)
	if result is not None:
		return result
	frappe.throw(
		_("Agent '{0}' has no running process for this conversation yet.").format(config["agent_id"])
	)


def _run_direct_api(config, conversation, message, context, stream=False):
	"""Single-shot / general chat. Persists the turn and calls the adapter's
	own (async) tool-calling loop for one exchange.

	With ``stream=True`` the same work runs on a thread and the reply's text
	is handed back as it is written, then the finished result follows as the
	handover event the buffered path already understands.

	The system prompt is composed the same way as on the two process paths.
	This used to send ``config["system_prompt"]`` on its own, which quietly
	dropped the agent's examples, its skills index and its guard rails: an
	agent that refused something inside a process map would do it in a chat,
	and the difference was invisible from the configuration.

	The turn is recorded as an AI Agent Run, like every turn on the two process
	paths. It used to be recorded nowhere: no run, so no prompt hash, no
	snapshot, no tokens, no cost and no steps. Every Direct API agent on a site
	was invisible to Insights, and this path's own guard rails could not be
	read back off a run.
	"""
	if stream:
		return _stream_direct_api(config, conversation, message, context)
	return _direct_api_turn(config, conversation, message)


def _stream_direct_api(config, conversation, message, context):
	"""Run the direct turn on a thread and yield its text as the model writes it.

	The adapter finds the queue on ``frappe.flags`` and puts each delta on it;
	this generator drains the queue while the model call runs. The thread gets
	a copy of this request's context or it would lose the site, the session
	and frappe.flags, and it is the only thing touching the database until it
	finishes, so the shared connection is never used from two threads at once.
	"""
	import contextvars
	import queue
	import threading

	from one_bpmn.ai_agent_conversations.agui.stream import HANDOVER_EVENT
	from one_bpmn.processa_engine.agent_runtime.turn_signal import LIVE_TEXT_QUEUE_FLAG

	deltas: "queue.Queue" = queue.Queue()
	done = object()
	outcome: dict = {}
	frappe.flags[LIVE_TEXT_QUEUE_FLAG] = deltas
	context_copy = contextvars.copy_context()

	def _work():
		try:
			outcome["result"] = context_copy.run(_direct_api_turn, config, conversation, message)
		except BaseException as exc:  # noqa: BLE001 - re-raised on the request thread
			outcome["error"] = exc
		finally:
			deltas.put(done)

	thread = threading.Thread(target=_work, daemon=True)
	thread.start()
	try:
		while True:
			item = deltas.get()
			if item is done:
				break
			yield {"type": "TEXT_MESSAGE_CONTENT", "delta": item}
	finally:
		frappe.flags[LIVE_TEXT_QUEUE_FLAG] = None
	thread.join()
	if "error" in outcome:
		raise outcome["error"]
	yield {"type": HANDOVER_EVENT, "result": outcome.get("result") or {}}


def _direct_api_turn(config, conversation, message):
	"""One direct chat exchange, recorded as a run, persisted as two messages."""
	from one_bpmn.ai_agent_observability import observability
	from one_bpmn.ai_agent_registry.provisioning.context_assembler import build_static_context_from_config
	from one_bpmn.processa_engine.agent_runtime.executor import ExecutorResult, TokenUsage
	from one_bpmn.processa_engine.agent_runtime.direct_api import run_coro_blocking
	from one_bpmn.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings
	from one_bpmn.ai_agent_conversations.chat_persistence import save_bot_message, save_user_message

	save_user_message(conversation, message)
	adapter = get_llm_adapter_from_settings(config)
	system_prompt = build_static_context_from_config(config)

	run = _begin_direct_run(config, system_prompt, message)
	try:
		completion = run_coro_blocking(adapter.complete(system=system_prompt, user=message))
	except Exception as exc:
		try:
			observability.finalize_ai_run_on_exception(run, exc)
		except Exception:
			frappe.log_error(title="AI chat: run not finalized", message=frappe.get_traceback())
		raise

	text = getattr(completion, "text", str(completion or ""))
	# The adapter hands back TurnRecord dataclasses; every recorder downstream
	# reads dicts, which is why the executor converts before it records
	# (direct_api.py: `trace = [asdict(turn) for turn in completion.trace]`).
	# Passing the raw objects cost a run on staging: record_selector_turns
	# raised AttributeError on turn.get, and the run sat at Running with no
	# tokens because finalizing came after it in the same try.
	trace = _as_dicts(getattr(completion, "trace", None) or [])
	prompt_tokens = getattr(completion, "prompt_tokens", 0) or 0
	completion_tokens = getattr(completion, "completion_tokens", 0) or 0

	# Two guards, not one. Recording the turns is the nice-to-have; finalizing
	# is what stops a finished run being reported as still running.
	try:
		observability.record_selector_turns(run, trace)
	except Exception:
		frappe.log_error(title="AI chat: turns not recorded", message=frappe.get_traceback())
	try:
		observability.finalize_ai_run(
			run,
			ExecutorResult(
				output=text,
				trace=trace,
				token_usage=TokenUsage(
					prompt_tokens=prompt_tokens,
					completion_tokens=completion_tokens,
					total_tokens=prompt_tokens + completion_tokens,
					cache_read_tokens=getattr(completion, "cache_read_tokens", 0) or 0,
					cache_write_tokens=getattr(completion, "cache_write_tokens", 0) or 0,
				),
			),
		)
	except Exception:
		frappe.log_error(title="AI chat: run not finalized", message=frappe.get_traceback())

	save_bot_message(conversation, text)
	return {"response": text}


def _as_dicts(trace: list) -> list:
	"""Turn a trace of TurnRecord dataclasses into the dicts the recorders read."""
	from dataclasses import asdict, is_dataclass

	return [asdict(turn) if is_dataclass(turn) else turn for turn in trace]


def _begin_direct_run(config: dict, system_prompt: str, message: str):
	"""Open the AI Agent Run for a direct chat turn, with its two prompt steps.

	Returns the run, or a stub when recording fails: observability treats a stub
	as "do not record", so every later call is a no-op and the turn carries on.
	A chat answer is worth more than its bookkeeping.

	There is no BPMN instance on this path, so the run carries none, and
	``bpmn_id`` is the agent's id — the only element identity a reader has here.
	"""
	from types import SimpleNamespace

	from one_bpmn.ai_agent_observability import observability
	from one_bpmn.processa_engine.agent_runtime.executor import ExecutorConfig

	try:
		run = observability.create_ai_run(
			SimpleNamespace(name="", process_model=""),
			bpmn_id=config.get("agent_id") or "direct_api",
			element_type="task",
			config=ExecutorConfig(
				backend="direct_api",
				provider_name=config.get("ai_provider") or "",
				agent_config_name=config.get("name") or "",
				model=config.get("ai_model") or "",
				system_prompt=system_prompt,
				user_prompt=message,
				# Pinned to 0.7 on purpose, not DEFAULT_TEMPERATURE.
				temperature=0.7,
			),
			bpmn_label=config.get("chat_mode_label") or config.get("agent_id") or "",
		)
		observability.record_ai_step(run, 1, "system", system_prompt)
		observability.record_ai_step(run, 2, "user", message)
		return run
	except Exception:
		frappe.log_error(title="AI chat: run not recorded", message=frappe.get_traceback())
		return SimpleNamespace(stub=True)


_RUNNERS = {
	"bpmn_map": _run_bpmn_map,
	"adk_stage_agent": _run_adk_stage_agent,
	"direct_api": _run_direct_api,
}


@frappe.whitelist()
def get_agent_surface(agent_id: str) -> dict:
	"""Everything the shared AgentChatPanel needs to draw an agent's chat
	surface, read from AI Agent Configuration: greeting,
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
				"collect_feedback",
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
		# Whether this agent's replies carry a rating control. The
		# panel reads it from here for the same reason it reads the greeting and
		# the icon from here: no agent-specific behaviour is hardcoded in a
		# component. Defaults on, so an agent configured before the field existed
		# collects feedback rather than silently not collecting it.
		"collect_feedback": bool(row.get("collect_feedback", 1)),
		"sample_prompts": sample_prompts,
	}
