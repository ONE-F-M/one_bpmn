# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""JSON-RPC protocol layer for the A2A server (WI-001932 / WI-0012009).

JSON-RPC is only the envelope — the fixed grammar for "which operation,
with what inputs, matched by what id, or which error". Everything after
the envelope is ordinary Processa.

Strict validation (WI-002009) happens here, before anything downstream
runs: the envelope against the contract's rpc_request schema, the inner
message against the message schema. Failures are rejected with the
protocol's standard error and logged to the security event log with
which fields failed — never processed.

Errors ride HTTP 200 as JSON-RPC error objects, per spec. Frappe's
default error handling would return the wrong shape, so responses are
written straight onto frappe.local.response.
"""

from __future__ import annotations

import json

import frappe

from one_bpmn.agents import a2a_contract


class A2AError(Exception):
	"""A protocol-level failure destined for a JSON-RPC error object."""

	def __init__(self, code_name: str, message: str, data=None):
		super().__init__(message)
		self.code = a2a_contract.error_code(code_name)
		self.message = message
		self.data = data


def parse_rpc_request() -> dict:
	"""Read and strictly validate the JSON-RPC envelope from the request
	body. Raises A2AError on anything malformed — nothing downstream runs."""
	raw = frappe.request.data if getattr(frappe.local, "request", None) else None
	if not raw:
		raise A2AError("INVALID_REQUEST", "empty request body")
	try:
		envelope = json.loads(raw)
	except Exception:
		raise A2AError("PARSE_ERROR", "request body is not valid JSON")

	if not isinstance(envelope, dict):
		raise A2AError("INVALID_REQUEST", "request body must be a JSON object")

	problems = a2a_contract.validate("rpc_request", envelope)
	if problems:
		log_validation_failure("input", problems, content=raw)
		raise A2AError("INVALID_REQUEST", "envelope failed schema validation", data=problems)
	return envelope


def validate_message_params(params: dict) -> dict:
	"""The inner message of message/send, strictly validated (WI-002009)."""
	message = (params or {}).get("message")
	if not isinstance(message, dict):
		raise A2AError("INVALID_PARAMS", "params.message is required")
	problems = a2a_contract.validate("message", message)
	if problems:
		log_validation_failure("input", problems, content=frappe.as_json(message))
		raise A2AError("INVALID_PARAMS", "message failed schema validation", data=problems)
	return message


def extract_text_parts(message: dict) -> str:
	"""Join the text parts; any other kind is rejected — v1 is text-only
	because nothing screens non-text content today."""
	texts: list[str] = []
	for part in message.get("parts") or []:
		kind = part.get("kind")
		if kind != "text":
			raise A2AError(
				"CONTENT_TYPE_NOT_SUPPORTED",
				f"unsupported part kind '{kind}' — this agent accepts text/plain only",
			)
		texts.append(part.get("text") or "")
	text = "\n".join(t for t in texts if t).strip()
	if not text:
		raise A2AError("INVALID_PARAMS", "message carries no text")
	return text


def read_trace(message: dict) -> dict:
	"""Delegation trace from message metadata (WI-002008). Values are
	advisory — limits are enforced locally regardless of what a remote
	claims — but they let a chain be counted across sites."""
	metadata = message.get("metadata") or {}
	return {
		"task_execution_id": metadata.get(a2a_contract.trace_key("taskExecutionId")),
		"delegation_depth": frappe.utils.cint(metadata.get(a2a_contract.trace_key("delegationDepth"))),
		"handoff_count": frappe.utils.cint(metadata.get(a2a_contract.trace_key("handoffCount"))),
	}


def task_to_wire(task, history: list | None = None) -> dict:
	"""The wire Task object for one A2A Task row."""
	status: dict = {"state": task.state}
	if task.status_message:
		status["message"] = agent_message(task.status_message, task_id=task.task_id)
	if task.get("modified"):
		status["timestamp"] = frappe.utils.get_datetime(task.modified).isoformat()

	wire = {
		"id": task.task_id,
		"contextId": task.context_id or "",
		"kind": "task",
		"status": status,
	}
	if task.artifacts:
		try:
			wire["artifacts"] = json.loads(task.artifacts)
		except Exception:
			wire["artifacts"] = []
	if history is not None:
		wire["history"] = history
	return wire


def agent_message(text: str, task_id: str | None = None) -> dict:
	message = {
		"role": "agent",
		"parts": [{"kind": "text", "text": text or ""}],
		"kind": "message",
	}
	if task_id:
		message["taskId"] = task_id
	return message


def respond_result(request_id, result: dict) -> None:
	_respond({"jsonrpc": "2.0", "id": request_id, "result": result})


def respond_error(request_id, code: int, message: str, data=None) -> None:
	error: dict = {"code": code, "message": message}
	if data is not None:
		error["data"] = data
	_respond({"jsonrpc": "2.0", "id": request_id, "error": error})


def _respond(payload: dict) -> None:
	"""Write the JSON-RPC object at the TOP level of the HTTP response —
	always 200, never wrapped in Frappe's {"message": ...} envelope."""
	frappe.local.response.update(payload)
	frappe.local.response["http_status_code"] = 200


def log_validation_failure(boundary: str, problems: list[str], content: str | None = None) -> None:
	"""WI-002009: every schema rejection becomes a security event carrying
	which fields failed and what was expected — through the one door all
	screening verdicts use. Never raises."""
	from one_bpmn.security.events import record_event

	record_event(
		boundary=boundary,
		stage="a2a-schema",
		action="Block",
		classifier="jsonschema",
		severity="Medium",
		content=content if isinstance(content, str) else None,
		detail="; ".join(problems),
	)
