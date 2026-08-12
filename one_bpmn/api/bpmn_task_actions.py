"""AMP email action callback endpoint for BPMN Process Instance tasks.

Handles secure in-email actions (Approve, Reject, Start Work, etc.)
from Gmail's AMP runtime, for any User Task belonging to a live BPMN
Process Instance — doctype-agnostic; whatever ``context_doctype`` the
instance points to. The request carries an HMAC-signed token — no
Frappe session cookie or CSRF token is present.

(Formerly ``todo_actions.py`` — renamed since the module has no
connection to the Frappe ``ToDo`` doctype; ``todo_actions.py`` still
exists as a thin backward-compatible re-export so any AMP email sent
before this rename keeps working. See ``one_bpmn.api.workflow_actions``
for the equivalent endpoint used by documents with no BPMN engine
behind them at all.)

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

	Since Frappe's ``allow_cors`` config handles basic CORS, this function
	only sets the AMP-specific headers that Frappe doesn't know about.
	We store them in ``frappe.flags._amp_extra_headers`` for the
	``after_request`` hook to apply.
	"""
	extra = {}

	# AMP-specific header: expose the source-origin header
	extra["Access-Control-Expose-Headers"] = "AMP-Access-Control-Allow-Source-Origin"

	# Echo back the __amp_source_origin query param
	source_origin = frappe.request.args.get("__amp_source_origin", "")
	if source_origin:
		extra["AMP-Access-Control-Allow-Source-Origin"] = source_origin

	frappe.flags._amp_extra_headers = extra


def apply_amp_headers(response, **kwargs):
	"""after_request hook — apply AMP-specific CORS headers to the response."""
	extra = getattr(frappe.flags, "_amp_extra_headers", None)
	if extra:
		for key, value in extra.items():
			response.headers[key] = value


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

		# ── Apply Frappe workflow action on the context document ────
		# complete_task only advances the BPMN engine.  We also need
		# to apply the workflow transition (Approve, Reject, etc.) on
		# the actual document so its status changes in ERPNext.
		instance_doc = frappe.get_doc("BPMN Process Instance", instance_name)
		ctx_dt = instance_doc.context_doctype
		ctx_dn = instance_doc.context_docname

		if ctx_dt and ctx_dn:
			try:
				from frappe.model.workflow import apply_workflow
				doc = frappe.get_doc(ctx_dt, ctx_dn)
				apply_workflow(doc, action)
				doc.save(ignore_permissions=True)
				frappe.db.commit()
			except Exception:
				# Log but don't fail — the BPMN task already completed
				frappe.log_error(
					title=f"AMP: Frappe workflow '{action}' failed on {ctx_dt}/{ctx_dn}",
					message=frappe.get_traceback(),
				)

		return {
			"message": _("{0} completed successfully.").format(action),
			"action": action,
			"status": result.get("status", ""),
		}

	except frappe.ValidationError as e:
		# "Task not found in active tasks" → already actioned
		error_msg = str(e)
		if "not found in the active tasks" in error_msg or "not in Waiting status" in error_msg:
			return {
				"message": _("This task has already been actioned."),
				"action": "Completed",
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


# ---------------------------------------------------------------------------
# Status endpoint (for amp-list live status on email open)
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_amp_task_status(status_token: str = "") -> dict:
	"""Return the current task status for an AMP email's amp-list.

	Called automatically when the email is opened in Gmail.
	The response drives conditional rendering: show action buttons
	if the task is still waiting, or a "completed" badge if already actioned.

	Args:
		status_token: HMAC-signed read-only token from :func:`generate_status_token`.

	Returns:
		AMP-list compatible dict with ``items`` array containing one item
		with keys: ``is_waiting``, ``is_completed``, ``action_taken``,
		``completed_by``, ``completed_at``.
	"""
	_set_amp_cors_headers()

	if not status_token:
		return {"items": [{"is_waiting": True}]}

	try:
		from one_bpmn.utils.token import verify_action_token

		payload = verify_action_token(status_token)
	except Exception:
		# Token expired or invalid — assume waiting (safe default)
		return {"items": [{"is_waiting": True}]}

	if payload.get("type") != "status":
		return {"items": [{"is_waiting": True}]}

	instance_name = payload["instance_name"]
	task_id = payload["task_id"]

	try:
		# Look up the task row
		task_row = frappe.db.get_value(
			"BPMN Active Task",
			{"parent": instance_name, "task_id": task_id},
			["status", "task_name", "assigned_user", "modified"],
			as_dict=True,
		)

		if not task_row or task_row.status == "Waiting":
			return {"items": [{"is_waiting": True}]}

		# Task is completed
		return {
			"items": [{
				"is_completed": True,
				"is_waiting": False,
				"action_taken": task_row.task_name or "Action",
				"completed_by": frappe.utils.get_fullname(task_row.assigned_user) if task_row.assigned_user else "",
				"completed_at": frappe.utils.format_datetime(task_row.modified, "d MMM, h:mm a") if task_row.modified else "",
			}]
		}
	except Exception:
		return {"items": [{"is_waiting": True}]}

