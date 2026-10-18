"""Generic AMP-for-Email action endpoint for plain Frappe-Workflow documents.

Mirrors ``one_bpmn.api.bpmn_task_actions.handle_amp_action`` (which advances a
BPMN Process Instance's task), but for any document whose approval is
driven by a standard Frappe Workflow instead. Unlike that endpoint, this
one has no knowledge of any specific doctype — every doctype/action
combination it's allowed to act on must be explicitly registered via the
``amp_workflow_actions`` hook, by whichever app owns that doctype.

Gmail's AMP XHR carries no Frappe session — an HMAC token from
``one_bpmn.utils.token.generate_doc_action_token`` is the sole trust
anchor, and is also the *only* source of which document/action is being
invoked. Extra POST fields (e.g. date inputs) are never written to the
document unless explicitly named in that action's registration — this
endpoint deliberately does not accept arbitrary field writes.

Registering a doctype/action
-----------------------------
Add to the owning app's ``hooks.py``::

	amp_workflow_actions = [
		{
			"doctype": "Leave Application",
			"action": "Approve",
			# Optional: only allow this action while the document's
			# workflow state equals this value (idempotency guard).
			"from_state": "Pending Approver",
		},
		{
			"doctype": "Leave Application",
			"action": "Propose New Dates",
			"from_state": "Pending Approver",
			# Optional: form-field-name -> document-field-name. Only
			# these fields may be written, and only with these names —
			# nothing else in the POST body is ever applied to the doc.
			"fields": {
				"propose_from_date": "custom_propose_from_date",
				"propose_to_date": "custom_propose_to_date",
			},
			"required_fields": ["propose_from_date", "propose_to_date"],
			# Optional: dotted path to fn(doc, form_data) called after
			# the fields above are set but before save — for computed
			# fields that depend on the submitted values.
			"compute": "one_fm.overrides.leave_application.compute_leave_propose_totals",
			# Optional: dotted path to fn(docname) called after the
			# workflow transition has been applied and committed. A
			# failure here is logged but does not affect the response —
			# the actual action already succeeded by this point.
			"after": "one_fm.overrides.leave_application.send_proposed_date_email",
		},
	]

Since this hook value is a plain list (not a nested dict), Frappe merges
registrations from multiple apps into one flat list without mangling
their contents — see ``frappe.append_hook``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_workflow_name, get_workflow_state_field


def _find_action_config(doctype: str, action: str) -> dict | None:
	"""Return the registered config for *doctype*/*action*, or ``None``."""
	for entry in frappe.get_hooks("amp_workflow_actions"):
		if entry.get("doctype") == doctype and entry.get("action") == action:
			return entry
	return None


def _get_workflow_state(doc) -> str | None:
	"""Return the current workflow state of *doc*, or ``None`` if it has no workflow."""
	workflow_name = get_workflow_name(doc.doctype)
	if not workflow_name:
		return None
	state_field = get_workflow_state_field(workflow_name)
	return doc.get(state_field)


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
def handle_workflow_action(token: str | None = None, **extra) -> dict:
	"""Process a plain-Frappe-Workflow action submitted from an AMP email.

	Args:
		token: HMAC-signed token from
			:func:`~one_bpmn.utils.token.generate_doc_action_token`.
		**extra: Any additional form fields submitted (e.g. date inputs
			for an action with registered ``fields``). Anything not
			explicitly named in the action's registration is ignored.

	Returns:
		dict with ``message`` (success) or ``error`` (failure) key, shaped
		for the amp-mustache ``submit-success`` / ``submit-error`` templates.
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

	doctype = payload.get("doctype")
	docname = payload.get("docname")
	action = payload.get("action")

	config = _find_action_config(doctype, action)
	if config is None:
		frappe.local.response.http_status_code = 403
		return {"error": _("Action not permitted from email.")}

	# Gmail AMP XHR has no Frappe session — the token is the sole trust
	# anchor, so we set the acting user from its (signed) payload.
	frappe.set_user(payload["user"])

	try:
		doc = frappe.get_doc(doctype, docname)

		from_state = config.get("from_state")
		if from_state and _get_workflow_state(doc) != from_state:
			return {
				"message": _("This item has already been actioned."),
				"action": "Completed",
			}

		field_map = config.get("fields") or {}
		required_fields = config.get("required_fields") or []
		for form_field in required_fields:
			if not extra.get(form_field):
				frappe.local.response.http_status_code = 400
				return {"error": _("Missing required field: {0}").format(form_field)}

		for form_field, doc_field in field_map.items():
			if form_field in extra and extra[form_field] is not None:
				doc.set(doc_field, extra[form_field])

		compute_fn = config.get("compute")
		if compute_fn:
			frappe.get_attr(compute_fn)(doc, extra)

		if field_map:
			doc.save(ignore_permissions=True)

		apply_workflow(doc, action)
		frappe.db.commit()

		after_fn = config.get("after")
		if after_fn:
			# The workflow transition above already succeeded and is
			# committed — a failure in this secondary step (e.g. a
			# notification email) must not surface as if the action
			# itself failed, since it didn't.
			try:
				frappe.get_attr(after_fn)(doc.name)
			except Exception:
				frappe.log_error(
					title="AMP workflow action: after-hook failed",
					message=frappe.get_traceback(),
				)

		return {
			"message": _("{0} completed successfully.").format(action),
			"action": action,
		}

	except frappe.ValidationError as e:
		frappe.local.response.http_status_code = 400
		return {"error": str(e)}
	except frappe.PermissionError as e:
		frappe.local.response.http_status_code = 403
		return {"error": _("Permission denied: {0}").format(str(e))}
	except Exception:
		frappe.log_error(
			title="AMP workflow action failed",
			message=frappe.get_traceback(),
		)
		frappe.local.response.http_status_code = 500
		return {"error": _("An error occurred. Please try in ERPNext.")}
