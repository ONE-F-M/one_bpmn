"""HMAC tokens for the AMP email callbacks.

A token is a base64url JSON payload, a dot and an HMAC-SHA256 hex signature keyed with the site secret.
Replay is refused by the task itself: a completed task_id is not active.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import time

import frappe


def _get_secret() -> str:
	"""The site's signing secret, the same one frappe.utils.verified_command uses."""
	from frappe.utils.verified_command import get_secret

	return get_secret()


def _sign(payload_json: str) -> str:
	"""HMAC-SHA256 hex signature of a JSON payload string."""
	return _hmac.new(
		_get_secret().encode("utf-8"),
		payload_json.encode("utf-8"),
		digestmod=hashlib.sha256,
	).hexdigest()


def _seal(payload: dict) -> str:
	"""The token for a payload: base64url of its sorted compact JSON, a dot, and its signature."""
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded}.{_sign(payload_json)}"


def generate_action_token(
	instance_name: str,
	task_id: str,
	action: str,
	user: str,
	expiry_hours: int = 72,
) -> str:
	"""A token that lets user run action on the task from an email button."""
	return _seal({
		"instance_name": instance_name,
		"task_id": task_id,
		"action": action,
		"user": user,
		"expires": int(time.time()) + (expiry_hours * 3600),
	})


def verify_action_token(token: str, allow_expired: bool = False) -> dict:
	"""The decoded payload of a token; raises AuthenticationError when tampered, ValidationError when expired.

	With allow_expired, an expired token with a valid signature is returned with an expired flag.
	"""
	if not token or "." not in token:
		raise frappe.AuthenticationError("Invalid token format.")

	payload_json, given_signature = token.rsplit(".", 1)

	try:
		payload_json = base64.urlsafe_b64decode(payload_json.encode("ascii")).decode("utf-8")
	except Exception:
		# Not base64: the payload is checked as raw JSON
		pass

	expected_signature = _sign(payload_json)
	if not _hmac.compare_digest(given_signature, expected_signature):
		raise frappe.AuthenticationError("Invalid or tampered token.")

	payload = json.loads(payload_json)

	expired = payload.get("expires", 0) < time.time()
	if allow_expired:
		payload["expired"] = expired
		return payload

	if expired:
		raise frappe.ValidationError(
			"This action link has expired. Please open the document in ERPNext."
		)

	return payload


CONVERSATION_TOKEN_KINDS = ("thread", "reply", "note")


def generate_conversation_token(
	instance_name: str,
	task_id: str,
	user: str,
	kind: str,
	expiry_hours: int = 72,
) -> str:
	"""A thread, reply or note token for the in-email conversation; it has no action, so it cannot complete the task."""
	if kind not in CONVERSATION_TOKEN_KINDS:
		raise ValueError(f"Unknown conversation token kind: {kind!r}")
	return _seal({
		"instance_name": instance_name,
		"task_id": task_id,
		"type": kind,
		"user": user,
		"expires": int(time.time()) + (expiry_hours * 3600),
	})


def generate_doc_action_token(
	doctype: str,
	docname: str,
	action: str,
	user: str,
	expiry_hours: int = 72,
) -> str:
	"""A token for a plain Frappe Workflow action, or a Comment, on a document."""
	return _seal({
		"doctype": doctype,
		"docname": docname,
		"action": action,
		"user": user,
		"expires": int(time.time()) + (expiry_hours * 3600),
	})


def generate_status_token(
	instance_name: str,
	task_id: str = "",
	expiry_days: int = 30,
	expiry_hours: int | None = None,
	user: str = "",
) -> str:
	"""A read-only token for the live task status the email fetches on open; expiry_hours overrides expiry_days."""
	lifetime = expiry_hours * 3600 if expiry_hours is not None else expiry_days * 86400
	payload = {
		"instance_name": instance_name,
		"task_id": task_id,
		"type": "status",
		"expires": int(time.time()) + lifetime,
	}
	if user:
		payload["user"] = user
	return _seal(payload)


def generate_file_token(
	file_name: str,
	doctype: str,
	docname: str,
	expiry_hours: int = 72,
) -> str:
	"""A token that downloads one File while it stays attached to doctype and docname."""
	return _seal({
		"file_name": file_name,
		"doctype": doctype,
		"docname": docname,
		"type": "file",
		"expires": int(time.time()) + (expiry_hours * 3600),
	})
