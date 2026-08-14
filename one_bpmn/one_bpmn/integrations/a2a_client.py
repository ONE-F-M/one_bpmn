# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""JSON-RPC client for remote A2A agents (WI-001933 / WI-002009).

Every call re-checks approval and re-runs the SSRF guard, not just the
first one: an entry can be revoked mid-flight, and a host that resolved
publicly a minute ago can resolve privately now (DNS rebinding). Cheap
checks, and they are the difference between an allow-list and a
suggestion.

Outbound messages are validated against the wire contract BEFORE
dispatch (WI-002009) — an invalid message is never sent.
"""

from __future__ import annotations

import json
import uuid

import frappe
from frappe import _

from one_bpmn.agents import a2a_contract
from one_bpmn.agents.a2a.protocol import log_validation_failure
from one_bpmn.one_bpmn.connectors.http_ops import _assert_host_allowed
from one_bpmn.one_bpmn.integrations.retry import call_with_retry

CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")


class A2AClientError(frappe.ValidationError):
	"""Local failure: not approved, invalid outbound message, transport dead."""


class A2ANotApprovedError(A2AClientError):
	"""The registry entry is not (or no longer) usable."""


class A2ARemoteError(A2AClientError):
	"""The remote answered with a JSON-RPC error object."""

	def __init__(self, code, message, data=None):
		super().__init__(f"remote A2A error {code}: {message}")
		self.code = code
		self.remote_message = message
		self.data = data


def require_approved(agent) -> "frappe.model.document.Document":
	"""Resolve and vet a registry entry. Accepts a name or a document."""
	doc = agent if hasattr(agent, "endpoint_url") else frappe.get_doc("A2A Remote Agent", agent)
	if not doc.enabled or doc.approval_status != "Approved":
		raise A2ANotApprovedError(
			_("Remote agent '{0}' is not approved for delegation.").format(doc.name)
		)
	return doc


def fetch_agent_card(agent) -> dict:
	"""GET the remote's card. Allowed pre-approval — the card is what an
	approver reviews — so this deliberately does NOT require_approved."""
	doc = agent if hasattr(agent, "endpoint_url") else frappe.get_doc("A2A Remote Agent", agent)
	base = (doc.endpoint_url or "").rstrip("/")
	if not base:
		raise A2AClientError(_("This remote agent has no endpoint URL."))

	last_error = None
	for path in CARD_PATHS:
		url = f"{base}{path}"
		try:
			_assert_host_allowed(url, allow_internal=bool(doc.allow_internal_hosts))
			response = call_with_retry(
				_session().get, url, timeout=doc.request_timeout or 30, headers=_headers(doc)
			)
			response.raise_for_status()
			card = response.json()
			if isinstance(card, dict) and card.get("skills"):
				return card
			last_error = A2AClientError(_("The response was not an agent card."))
		except Exception as exc:  # noqa: BLE001 — try the next path, report the last
			last_error = exc
	raise A2AClientError(
		_("Could not fetch an agent card from {0}: {1}").format(base, last_error)
	)


def message_send(
	agent,
	text: str,
	task_id: str | None = None,
	context_id: str | None = None,
	metadata: dict | None = None,
) -> dict:
	"""Send (or continue) a task. Returns the wire Task or Message."""
	message: dict = {
		"role": "user",
		"parts": [{"kind": "text", "text": text or ""}],
		"kind": "message",
		"messageId": str(uuid.uuid4()),
	}
	if task_id:
		message["taskId"] = task_id
	if context_id:
		message["contextId"] = context_id
	if metadata:
		message["metadata"] = metadata

	# WI-002009: validate before dispatch — never send an invalid message.
	problems = a2a_contract.validate("message", message)
	if problems:
		log_validation_failure("output", problems, content=frappe.as_json(message))
		raise A2AClientError(
			_("Refusing to send an invalid A2A message: {0}").format("; ".join(problems))
		)

	return _rpc(agent, "message/send", {"message": message})


def tasks_get(agent, remote_task_id: str, history_length: int | None = None) -> dict:
	params: dict = {"id": remote_task_id}
	if history_length:
		params["historyLength"] = int(history_length)
	return _rpc(agent, "tasks/get", params)


def tasks_cancel(agent, remote_task_id: str) -> dict:
	return _rpc(agent, "tasks/cancel", {"id": remote_task_id})


def set_push_config(agent, remote_task_id: str, url: str, token: str) -> dict:
	"""Ask a remote to call us when this task changes (WI-001933 follow-up).

	The token is echoed back to us on every callback and is the only thing
	authenticating it, so it is minted per task and never reused.
	"""
	return _rpc(
		agent,
		"tasks/pushNotificationConfig/set",
		{
			"taskId": remote_task_id,
			"pushNotificationConfig": {"url": url, "token": token},
		},
	)


def _rpc(agent, method: str, params: dict) -> dict:
	doc = require_approved(agent)
	url = (doc.endpoint_url or "").rstrip("/")
	_assert_host_allowed(url, allow_internal=bool(doc.allow_internal_hosts))

	envelope = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
	response = call_with_retry(
		_session().post,
		url,
		json=envelope,
		timeout=doc.request_timeout or 30,
		headers={**_headers(doc), "Content-Type": "application/json"},
	)
	response.raise_for_status()
	try:
		payload = response.json()
	except Exception:
		raise A2AClientError(_("The remote agent did not answer with JSON."))

	if not isinstance(payload, dict):
		raise A2AClientError(_("The remote agent's answer was not a JSON-RPC object."))
	if payload.get("error"):
		error = payload["error"]
		raise A2ARemoteError(error.get("code"), error.get("message"), error.get("data"))
	result = payload.get("result")
	if not isinstance(result, dict):
		raise A2AClientError(_("The remote agent's answer carried no result."))
	return result


def _headers(doc) -> dict:
	"""Auth header for this entry; the secret is decrypted per call and
	never cached."""
	scheme = doc.auth_scheme or "None"
	if scheme == "None":
		return {}
	secret = doc.get_password("credential", raise_exception=False)
	if not secret:
		return {}
	if scheme == "Bearer":
		return {"Authorization": f"Bearer {secret}"}
	return {(doc.auth_header_name or "Authorization"): secret}


def _session():
	import requests

	return requests


def remote_text(result: dict) -> str:
	"""Best-effort reply text from a wire Task or Message."""
	if not isinstance(result, dict):
		return ""
	if result.get("kind") == "message" or "parts" in result:
		return "\n".join(
			part.get("text") or "" for part in result.get("parts") or [] if part.get("kind") == "text"
		).strip()

	# Artifacts ARE the result; status.message is a progress note that often
	# repeats it. Prefer artifacts and fall back — reading both concatenates
	# the same answer twice against any server that fills in both.
	texts: list[str] = []
	for artifact in result.get("artifacts") or []:
		texts += [
			part.get("text") or ""
			for part in artifact.get("parts") or []
			if part.get("kind") == "text"
		]
	if not any(texts):
		status_message = (result.get("status") or {}).get("message") or {}
		texts = [
			part.get("text") or ""
			for part in status_message.get("parts") or []
			if part.get("kind") == "text"
		]
	return "\n".join(t for t in texts if t).strip()


def remote_state(result: dict) -> str | None:
	if not isinstance(result, dict):
		return None
	if result.get("kind") == "message":
		return "completed"
	return ((result.get("status") or {}).get("state")) or None
