"""Comment submission API endpoint for AMP email forms.

Provides a whitelisted Frappe endpoint that allows submitting a comment on
a document directly from an AMP-powered email. Mirrors
``one_bpmn.api.bpmn_task_actions.handle_amp_action`` — Gmail's AMP XHR carries
no Frappe session, so an HMAC token (generated with
:func:`~one_bpmn.utils.token.generate_doc_action_token`, action=
``"Comment"``) is the sole trust anchor and the source of *which* document
is being commented on, rather than trusting client-submitted doctype/name
fields directly.

Typical usage from an AMP ``<amp-form>``::

	POST /api/method/one_bpmn.api.comment.submit_comment
	Content-Type: application/x-www-form-urlencoded

	comment=Looks+good&token=<sealed-token>
"""

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
def submit_comment(token: str | None = None, comment: str | None = None) -> dict:
	"""Add a comment to a Frappe document from an AMP email.

	Args:
		token: HMAC-signed token from
			:func:`~one_bpmn.utils.token.generate_doc_action_token`
			(action must be ``"Comment"``), encoding the target
			doctype/docname and the acting user.
		comment: The comment body text. Must be non-empty after stripping
			whitespace.

	Returns:
		dict with ``message`` (success) or ``error`` (failure) key, shaped
		like the other AMP action endpoints for consistency.
	"""
	from one_bpmn.api.bpmn_task_actions import _set_amp_cors_headers

	_set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

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

	if payload.get("action") != "Comment":
		frappe.local.response.http_status_code = 403
		return {"error": _("Invalid token.")}

	if not comment or not comment.strip():
		frappe.local.response.http_status_code = 400
		return {"error": _("Comment cannot be empty.")}

	# Gmail AMP XHR has no Frappe session — the token is the sole trust
	# anchor, so we set the acting user from its (signed) payload.
	frappe.set_user(payload["user"])

	doctype = payload.get("doctype")
	name = payload.get("docname")

	try:
		if not frappe.has_permission(doctype, "read", name):
			frappe.local.response.http_status_code = 403
			return {"error": _("You do not have permission to comment on this document.")}

		doc = frappe.get_doc(doctype, name)
		doc.add_comment("Comment", comment.strip())
		frappe.db.commit()

		return {"message": _("Comment submitted successfully."), "action": "Comment"}

	except frappe.PermissionError as e:
		frappe.local.response.http_status_code = 403
		return {"error": _("Permission denied: {0}").format(str(e))}
	except Exception:
		frappe.log_error(
			title="AMP comment submission failed",
			message=frappe.get_traceback(),
		)
		frappe.local.response.http_status_code = 500
		return {"error": _("An error occurred. Please try in ERPNext.")}
