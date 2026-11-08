"""HMAC token utility for AMP email action callbacks.

Generates and verifies signed tokens that are embedded in AMP email
action buttons.  When a user clicks "Approve" inside Gmail, the token
is POSTed to :func:`one_bpmn.api.todo_actions.handle_amp_action`,
which verifies the signature before delegating to ``complete_task()``.

Security model
~~~~~~~~~~~~~~
- Uses HMAC-SHA256 with the Frappe site's encryption key
  (via :func:`frappe.utils.verified_command.get_secret`).
- The token is a JSON payload + ``.`` + hex signature.
- **Replay protection** is inherent: once ``complete_task()`` advances
  the workflow, the ``task_id`` is no longer in ``active_tasks``, so
  a second use returns "already actioned".
- ``expires`` is a backstop for tokens that are never used.

Typical usage::

	from one_bpmn.utils.token import generate_action_token, verify_action_token

	token = generate_action_token("BPMN-INST-001", "task-uuid", "Approve", "user@example.com")
	payload = verify_action_token(token)  # raises on failure
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import time

import frappe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_secret() -> str:
	"""Return the site's HMAC signing secret.

	Reuses the same secret as ``frappe.utils.verified_command``.
	"""
	from frappe.utils.verified_command import get_secret

	return get_secret()


def _sign(payload_json: str) -> str:
	"""HMAC-SHA256 sign a JSON payload string."""
	return _hmac.new(
		_get_secret().encode("utf-8"),
		payload_json.encode("utf-8"),
		digestmod=hashlib.sha256,
	).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_action_token(
	instance_name: str,
	task_id: str,
	action: str,
	user: str,
	expiry_hours: int = 72,
) -> str:
	"""Generate an HMAC-signed token for an email action button.

	Args:
		instance_name: BPMN Process Instance document name.
		task_id: SpiffWorkflow task UUID (from ``active_tasks``).
		action: Action name (e.g. ``"Approve"``).
		user: Frappe user (email) who is allowed to execute the action.
		expiry_hours: Hours until the token expires (default 72 = 3 days).

	Returns:
		A sealed string in the form ``<json_payload>.<hmac_hex>``.
	"""
	payload = {
		"instance_name": instance_name,
		"task_id": task_id,
		"action": action,
		"user": user,
		"expires": int(time.time()) + (expiry_hours * 3600),
	}
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	signature = _sign(payload_json)
	# Base64url-encode to avoid HTML attribute escaping issues
	import base64
	encoded_payload = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded_payload}.{signature}"


def verify_action_token(token: str, allow_expired: bool = False) -> dict:
	"""Verify and decode an action token.

	Args:
		token: The sealed token string from :func:`generate_action_token`.
		allow_expired: When true, an expired token with a valid signature is
			returned with an ``expired`` flag instead of raising.

	Returns:
		The decoded payload dict with keys:
		``instance_name``, ``task_id``, ``action``, ``user``, ``expires``
		(plus ``expired`` when ``allow_expired`` is true).

	Raises:
		frappe.AuthenticationError: If the token signature is invalid
			(tampered payload).
		frappe.ValidationError: If the token has expired.
		ValueError: If the token format is malformed.
	"""
	if not token or "." not in token:
		raise frappe.AuthenticationError("Invalid token format.")

	# Split on the LAST dot (payload itself might not have dots, but
	# the separator is always the last one since the signature is hex).
	payload_json, given_signature = token.rsplit(".", 1)

	# Decode base64url payload
	import base64
	try:
		payload_json = base64.urlsafe_b64decode(payload_json.encode("ascii")).decode("utf-8")
	except Exception:
		# Fallback: try treating as raw JSON (legacy tokens)
		pass

	# Recompute signature on the decoded JSON
	expected_signature = _sign(payload_json)
	if not _hmac.compare_digest(given_signature, expected_signature):
		raise frappe.AuthenticationError("Invalid or tampered token.")

	payload = json.loads(payload_json)

	# Check expiry only after the signature has been verified
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
	"""Generate an HMAC-signed token for the in-email conversation endpoints.

	Same sealing scheme as :func:`generate_action_token`, plus a ``type``
	of ``"thread"``, ``"reply"`` or ``"note"``. The token carries no
	``action``: it can read the thread, post a reply or add a note, and
	:func:`one_bpmn.api.todo_actions.handle_amp_action` refuses any token
	with a ``type``, so it can never complete the task by itself.
	Verified with :func:`verify_action_token`.

	Args:
		instance_name: BPMN Process Instance document name.
		task_id: SpiffWorkflow task UUID.
		user: Frappe user (email) the endpoint acts as.
		kind: ``"thread"``, ``"reply"`` or ``"note"``.
		expiry_hours: Hours until the token expires (default 72 = 3 days).

	Returns:
		A sealed string in the form ``<base64_payload>.<hmac_hex>``.
	"""
	if kind not in CONVERSATION_TOKEN_KINDS:
		raise ValueError(f"Unknown conversation token kind: {kind!r}")
	payload = {
		"instance_name": instance_name,
		"task_id": task_id,
		"type": kind,
		"user": user,
		"expires": int(time.time()) + (expiry_hours * 3600),
	}
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	signature = _sign(payload_json)
	import base64
	encoded_payload = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded_payload}.{signature}"


def generate_doc_action_token(
	doctype: str,
	docname: str,
	action: str,
	user: str,
	expiry_hours: int = 72,
) -> str:
	"""Generate an HMAC-signed token for a plain Frappe-workflow action email.

	Same sealing scheme as :func:`generate_action_token`, but keyed on
	``doctype``/``docname`` instead of a BPMN instance/task — for documents
	whose approval is driven by a standard Frappe Workflow rather than a
	BPMN Process Instance. Verified with the same :func:`verify_action_token`.

	Args:
		doctype: Target DocType (e.g. ``"Leave Application"``).
		docname: Target document name.
		action: Workflow action name (e.g. ``"Approve"``).
		user: Frappe user (email) who is allowed to execute the action.
		expiry_hours: Hours until the token expires (default 72 = 3 days).

	Returns:
		A sealed string in the form ``<json_payload>.<hmac_hex>``.
	"""
	payload = {
		"doctype": doctype,
		"docname": docname,
		"action": action,
		"user": user,
		"expires": int(time.time()) + (expiry_hours * 3600),
	}
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	signature = _sign(payload_json)
	import base64
	encoded_payload = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded_payload}.{signature}"


def generate_status_token(
	instance_name: str,
	task_id: str = "",
	expiry_days: int = 30,
	expiry_hours: int | None = None,
	user: str = "",
) -> str:
	"""Generate a read-only HMAC token for checking task status.

	This token is embedded in the ``amp-list`` src URL so the email
	can fetch live status on open.  It grants no action capability.

	Args:
		instance_name: BPMN Process Instance document name.
		task_id: SpiffWorkflow task UUID (empty for a document-only status token).
		expiry_days: Days until the token expires (default 30).
		expiry_hours: Hours until the token expires; overrides ``expiry_days``.
		user: Frappe user (email) the email was sent to; omitted from the token when empty.

	Returns:
		A sealed string in the form ``<base64_payload>.<hmac_hex>``.
	"""
	lifetime = expiry_hours * 3600 if expiry_hours is not None else expiry_days * 86400
	payload = {
		"instance_name": instance_name,
		"task_id": task_id,
		"type": "status",
		"expires": int(time.time()) + lifetime,
	}
	if user:
		payload["user"] = user
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	signature = _sign(payload_json)
	import base64
	encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded}.{signature}"


def generate_file_token(
	file_name: str,
	doctype: str,
	docname: str,
	expiry_hours: int = 72,
) -> str:
	"""Generate an HMAC-signed token that downloads one attached file.

	Same sealing scheme as :func:`generate_action_token`, with ``type``
	``"file"``. The token grants read access to a single File only while
	that File stays attached to the signed ``doctype``/``docname``.

	Args:
		file_name: Name of the File document (not its display file name).
		doctype: DocType the file must be attached to.
		docname: Name of the document the file must be attached to.
		expiry_hours: Hours until the token expires (default 72 = 3 days).

	Returns:
		A sealed string in the form ``<base64_payload>.<hmac_hex>``.
	"""
	payload = {
		"file_name": file_name,
		"doctype": doctype,
		"docname": docname,
		"type": "file",
		"expires": int(time.time()) + (expiry_hours * 3600),
	}
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	signature = _sign(payload_json)
	import base64
	encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded}.{signature}"

