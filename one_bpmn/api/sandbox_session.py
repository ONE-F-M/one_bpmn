"""The calls a sandbox Job container makes to Processa: register once, poll for its next command, post each result."""

import json

import frappe

from one_bpmn.one_bpmn.connectors import agent_sandbox_session as sessions

REFUSED = {"accepted": False}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register() -> dict:
	"""Exchange the one-time token for the session settings and key."""
	body = _body()
	settings = sessions.register(str(body.get("session") or ""), str(body.get("token") or "")) if body else None
	return {"accepted": True, **settings} if settings else REFUSED


@frappe.whitelist(allow_guest=True, methods=["POST"])
def next_command() -> dict:
	"""The next pending command, or none. Each call also shows the session is alive."""
	session = _signed_session()
	if not session:
		return REFUSED
	return {"accepted": True, "command": sessions.next_command(session)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def post_result() -> dict:
	"""The result of command seq, signed with the session key."""
	session = _signed_session()
	if not session:
		return REFUSED
	body = _body()
	result = body.get("result")
	if not (isinstance(result, dict) and isinstance(body.get("seq"), int) and body.get("status") in ("ok", "error")):
		return REFUSED
	return {"accepted": sessions.accept_result(session, body["seq"], body["status"], result)}


def _body() -> dict:
	try:
		body = json.loads(frappe.request.get_data() or b"{}")
	except ValueError:
		return {}
	return body if isinstance(body, dict) else {}


def _signed_session():
	return sessions.verified_session(_body(), (frappe.get_request_header("X-Signature") or "").strip(), frappe.request.get_data())
