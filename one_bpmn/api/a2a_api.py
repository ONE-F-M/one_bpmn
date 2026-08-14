# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A protocol HTTP surface (WI-001931 / WI-001932).

Discovery is deliberately guest-readable — the spec expects an
unauthenticated card fetch — and deliberately unable to distinguish
"no such agent" from "agent not exposed": both are the same 404.

There is no /.well-known/ route in v1: this is a multi-agent site and
Frappe reserves that path for the web router, so the card URL is this
documented /api/method address instead.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from one_bpmn.agents.a2a import protocol, push, task_store
from one_bpmn.agents.a2a.card import build_agent_card
from one_bpmn.agents.a2a.principal import client_may_invoke, get_client_for_user
from one_bpmn.agents.a2a.protocol import A2AError


@frappe.whitelist(allow_guest=True, methods=["GET"])
def agent_card(agent_id: str) -> dict:
	"""The public Agent Card for one exposed agent (WI-001931)."""
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
	from one_bpmn.agents.a2a_contract import terminal_states
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_a2a_resume,
	)
	from one_bpmn.one_bpmn.integrations import a2a_client

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
		_enqueue_a2a_resume(task.instance, task.wf_task_id, task.name)
	elif state in ("failed", "canceled", "rejected"):
		task.db_set(
			{
				"state": state,
				"error_message": (text or state)[:500],
				"completed_at": frappe.utils.now_datetime(),
			},
			update_modified=True,
		)
		_enqueue_a2a_resume(task.instance, task.wf_task_id, task.name)
	elif state == "input-required":
		task.db_set({"state": "input-required"}, update_modified=True)
		if task.instance:
			instance = frappe.get_doc("BPMN Process Instance", task.instance)
			instance._on_a2a_input_required(task.name, text)
	else:
		task.db_set({"state": state}, update_modified=True)

	return {"accepted": True}


# ── The JSON-RPC door (WI-001932) ─────────────────────────────────────────────


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

	if config.agent_type == "Background":
		_start_background(task, config, text)
	else:
		_run_chat_turn(task, config, text)

	task_store.refresh_state(task)
	return protocol.task_to_wire(task)


def _run_chat_turn(task, config, text: str) -> None:
	"""Chat path: the whole existing turn machinery, screening included,
	via the standard invocation entry point."""
	from one_bpmn.api.agent_invocation import invoke_agent
	from one_bpmn.security.rate_limit import RateLimited

	try:
		result = invoke_agent(config["agent_id"], text)
	except RateLimited as refusal:
		task.db_set({"state": "rejected", "error_message": str(refusal)[:500]}, update_modified=True)
		task.reload()
		return
	except Exception:
		frappe.log_error(title="A2A message/send turn failed", message=frappe.get_traceback())
		task.db_set(
			{"state": "failed", "error_message": "the agent's turn failed"}, update_modified=True
		)
		task.reload()
		return

	conversation = result.get("conversation")
	updates = {"conversation": conversation}
	instance = task_store.find_instance(conversation) if conversation else None
	if instance:
		updates["instance"] = instance
	task.db_set(updates, update_modified=False)
	task.reload()

	suspended = None
	if instance:
		from one_bpmn.agents.checkpoint import get_suspended_run

		suspended = get_suspended_run(instance)
	if suspended:
		pending = frappe.db.get_value("AI Agent Run", suspended, "pending_human_task")
		task.db_set(
			{
				"state": "input-required",
				"agent_run": suspended,
				"pending_human_task": pending,
				"status_message": (result.get("response") or "")[:500],
			},
			update_modified=True,
		)
		task.reload()
	else:
		task_store.store_result(task, result.get("response") or "")


def _start_background(task, config, text: str) -> None:
	"""Background path (WI-001932 revision): no Chat Conversation. The
	A2A Task row itself is the trigger document — an A2A-startable map
	(start event on A2A Task insert) has already started on insert; here
	we just find and bind the instance."""
	from one_bpmn.agents.agent_provisioning import is_a2a_startable_map

	if not is_a2a_startable_map(config.process_model):
		task.db_set(
			{"state": "rejected", "error_message": "agent not available to this caller"},
			update_modified=True,
		)
		task.reload()
		return

	instance = task_store.find_instance_for_task(task.name)
	if not instance:
		# The insert happened before agent_configuration could be matched by
		# a map whose start condition needs it — re-fire the same conditional
		# gate the universal trigger uses.
		try:
			from one_bpmn.one_bpmn.trigger import _maybe_start_instance

			_maybe_start_instance(frappe.get_doc("A2A Task", task.name), config.process_model)
			instance = task_store.find_instance_for_task(task.name)
		except Exception:
			frappe.log_error(title="A2A background start failed", message=frappe.get_traceback())

	if not instance:
		task.db_set(
			{"state": "failed", "error_message": "no process started for this task"},
			update_modified=True,
		)
		task.reload()
		return
	task.db_set({"instance": instance, "state": "working"}, update_modified=True)
	task.reload()


def _continue_task(message: dict, text: str) -> dict:
	"""The caller answers an input-required pause. This path bypasses
	invoke_agent, so screening is mirrored explicitly before the answer
	reaches the suspended run (WI-001932)."""
	task = task_store.get_task_for_principal(message["taskId"])
	task_store.refresh_state(task)
	if task.state != "input-required":
		raise A2AError("INVALID_PARAMS", "task is not waiting for input")
	if not (task.instance and task.pending_human_task):
		raise A2AError("INTERNAL_ERROR", "task has no resumable pause")

	text = _screen_continuation(task, text)

	from one_bpmn.api.instance_api import complete_task

	complete_task(task.instance, task.pending_human_task, json.dumps({"response": text}))
	task.db_set(
		{"state": "working", "pending_human_task": "", "status_message": ""}, update_modified=True
	)
	task.reload()
	return protocol.task_to_wire(task)


def _screen_continuation(task, text: str) -> str:
	"""Mirror of invoke_agent's input screening chain for the one path
	that bypasses it: rate limit, turn correlation, PII, injection."""
	from one_bpmn.security import pii as _pii
	from one_bpmn.security import rate_limit as _rate_limit
	from one_bpmn.security import turn as _turn
	from one_bpmn.security.injection import screen_for_injection

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
			from one_bpmn.utils.chat_persistence import close_conversation

			close_conversation(locked.conversation)
		except Exception:
			frappe.log_error(title="A2A cancel: close_conversation failed", message=frappe.get_traceback())
	locked.reload()
	return protocol.task_to_wire(locked)
