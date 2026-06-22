"""AMP email action callback endpoint.

Handles secure in-email actions (Approve, Reject, etc.) from Gmail's
AMP runtime.  The request carries an HMAC-signed token — no Frappe
session cookie or CSRF token is present.

Flow::

	Gmail AMP XHR  ─→  handle_amp_action(token, comment?)
	                      │
	                      ├─ verify_action_token(token)  → payload
	                      ├─ frappe.set_user(payload.user)
	                      ├─ complete_task(instance, task_id, data)
	                      │     └─ advance() → workflow moves forward
	                      └─ return AMP-shaped JSON

CORS
~~~~
Gmail sends an OPTIONS preflight and requires specific response headers.
The endpoint handles both OPTIONS and POST.  For production, an nginx
snippet is provided at ``templates/deployment/amp_cors_nginx.conf``
for faster preflight handling at the proxy layer.
"""

from __future__ import annotations

import json

import frappe
from frappe import _


# ---------------------------------------------------------------------------
# AMP CORS helpers
# ---------------------------------------------------------------------------

_AMP_ALLOWED_ORIGINS = frozenset({
	"https://mail.google.com",
	"https://amp.gmail.dev",
})


def _set_amp_cors_headers() -> None:
	"""Set AMP-required CORS headers on the Frappe response.

	Gmail AMP requires:
	- ``Access-Control-Allow-Origin`` matching the request Origin
	- ``AMP-Access-Control-Allow-Source-Origin`` echoing ``__amp_source_origin``
	- ``Access-Control-Expose-Headers`` listing the AMP header
	"""
	# Ensure headers dict exists (it's None by default in Frappe)
	if not frappe.local.response.get("headers"):
		frappe.local.response["headers"] = {}

	headers = frappe.local.response["headers"]

	origin = (frappe.request.headers.get("Origin") or "").rstrip("/")
	if origin in _AMP_ALLOWED_ORIGINS:
		headers["Access-Control-Allow-Origin"] = origin

	headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
	headers["Access-Control-Allow-Headers"] = "Content-Type, AMP-Same-Origin"
	headers["Access-Control-Expose-Headers"] = "AMP-Access-Control-Allow-Source-Origin"

	# Echo back the __amp_source_origin query param
	source_origin = frappe.request.args.get("__amp_source_origin", "")
	if source_origin:
		headers["AMP-Access-Control-Allow-Source-Origin"] = source_origin


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
def handle_amp_action(token: str | None = None, comment: str | None = None) -> dict:
	"""Process an action submitted from an AMP email button.

	Args:
		token: HMAC-signed token from :func:`~one_bpmn.utils.token.generate_action_token`.
		comment: Optional comment text submitted with the action.

	Returns:
		dict with ``message`` (success) or ``error`` (failure) key,
		shaped for amp-mustache ``submit-success`` / ``submit-error``
		templates.
	"""
	# Always set CORS headers (even for OPTIONS)
	_set_amp_cors_headers()

	# Handle OPTIONS preflight — return immediately
	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	# ── Verify token ───────────────────────────────────────────────
	if not token:
		frappe.local.response.http_status_code = 403
		return {"error": _("Missing action token.")}

	try:
		from one_bpmn.utils.token import verify_action_token

		payload = verify_action_token(token)
	except frappe.AuthenticationError:
		frappe.local.response.http_status_code = 403
		return {"error": _("Invalid or tampered token.")}
	except frappe.ValidationError as e:
		frappe.local.response.http_status_code = 403
		return {"error": str(e)}

	# ── Set the authenticated user ─────────────────────────────────
	# Gmail AMP XHR has no Frappe session — the token is the sole
	# trust anchor.  complete_task() checks frappe.session.user for
	# the assignee match, so we must set it here.
	user = payload["user"]
	frappe.set_user(user)

	instance_name = payload["instance_name"]
	task_id = payload["task_id"]
	action = payload["action"]

	# Build data payload for complete_task
	task_data = {"action": action}
	if comment and comment.strip():
		task_data["comment"] = comment.strip()

	# ── Delegate to complete_task ──────────────────────────────────
	try:
		from one_bpmn.api.instance_api import complete_task

		result = complete_task(
			instance_name=instance_name,
			task_id=task_id,
			data=json.dumps(task_data),
		)

		return {
			"message": _("✓ {0} completed successfully.").format(action),
			"status": result.get("status", ""),
		}

	except frappe.ValidationError as e:
		# "Task not found in active tasks" → already actioned
		error_msg = str(e)
		if "not found in the active tasks" in error_msg or "not in Waiting status" in error_msg:
			return {
				"message": _("This task has already been actioned."),
			}
		# Other validation errors (bad action name, etc.)
		frappe.local.response.http_status_code = 400
		return {"error": error_msg}

	except frappe.PermissionError as e:
		frappe.local.response.http_status_code = 403
		return {"error": _("Permission denied: {0}").format(str(e))}

	except Exception as e:
		frappe.log_error(
			title="AMP action callback failed",
			message=frappe.get_traceback(),
		)
		frappe.local.response.http_status_code = 500
		return {"error": _("An error occurred. Please try in ERPNext.")}
