"""Endpoints the AMP and HTML task emails call. Gmail sends no Frappe session, so the signed token is the only trust anchor."""

from __future__ import annotations

import html as _html
import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from one_bpmn.processa_engine.notifications import actions


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
def handle_amp_action(
	token: str | None = None,
	comment: str | None = None,
	reason_chip: str | None = None,
	reason_text: str | None = None,
	reason_lang: str | None = None,
) -> dict:
	"""Complete the task with the action a button's token names; returns message or error for amp-mustache.

	The reason panel always posts reason_lang, with the picked reason_chip index and the typed reason_text.
	"""
	actions.set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	if not token:
		frappe.local.response.http_status_code = 403
		return {"error": _("Missing action token.")}

	try:
		from one_bpmn.processa_engine.notifications.token import verify_action_token

		payload = verify_action_token(token)
	except frappe.AuthenticationError:
		frappe.local.response.http_status_code = 403
		return {"error": _("Invalid or tampered token.")}
	except frappe.ValidationError as e:
		frappe.local.response.http_status_code = 403
		return {"error": str(e)}

	# A conversation or status token has a type; an action token has none
	if payload.get("type"):
		frappe.local.response.http_status_code = 403
		return {"error": _("This link cannot be used to action a task.")}

	# complete_task matches the assignee against the session user
	user = payload["user"]
	frappe.set_user(user)

	instance_name = payload["instance_name"]
	task_id = payload["task_id"]
	action = payload["action"]

	task_data = {"action": action}
	if comment and comment.strip():
		task_data["comment"] = comment.strip()

	try:
		from one_bpmn.api.instances import complete_task

		saved_reason = None
		if reason_lang is not None:
			saved_reason = actions.save_reason(instance_name, task_id, action, reason_chip, reason_text, reason_lang)
		if saved_reason:
			task_data["comment"] = saved_reason["reason"]

		result = complete_task(
			instance_name=instance_name,
			task_id=task_id,
			data=json.dumps(task_data),
		)

		# complete_task only advances the engine; the document's own workflow moves here
		instance_doc = frappe.get_doc("BPMN Process Instance", instance_name)
		ctx_dt = instance_doc.context_doctype
		ctx_dn = instance_doc.context_docname

		from frappe.model.workflow import get_workflow_name

		if ctx_dt and ctx_dn and get_workflow_name(ctx_dt):
			try:
				from frappe.model.workflow import apply_workflow
				doc = frappe.get_doc(ctx_dt, ctx_dn)
				apply_workflow(doc, action)
				doc.save(ignore_permissions=True)  # the token user passed apply_workflow's transition check
				frappe.db.commit()
			except Exception:
				# The BPMN task is already complete, so this logs and does not fail
				frappe.log_error(
					title=f"AMP: Frappe workflow '{action}' failed on {ctx_dt}/{ctx_dn}",
					message=frappe.get_traceback(),
				)

		return {
			"message": _("You chose {0}.").format(action),
			"action": action,
			"status": result.get("status", ""),
			**actions.receipt(instance_name, ctx_dt, ctx_dn, action),
			"reason_saved": saved_reason["saved"] if saved_reason else {"en": "", "ar": ""},
		}

	except frappe.ValidationError as e:
		# An inactive or non-Waiting task means someone already acted
		error_msg = str(e)
		if "not found in the active tasks" in error_msg or "not in Waiting status" in error_msg:
			return {
				"message": _("Someone has already acted on this task."),
				"action": "Completed",
			}
		frappe.local.response.http_status_code = 400
		return {"error": error_msg}

	except frappe.PermissionError as e:
		frappe.local.response.http_status_code = 403
		return {"error": _("Permission denied: {0}").format(str(e))}

	except Exception:
		frappe.log_error(
			title="AMP action callback failed",
			message=frappe.get_traceback(),
		)
		frappe.local.response.http_status_code = 500
		return {"error": _("An error occurred. Please try in ERPNext.")}


@frappe.whitelist(allow_guest=True, methods=["GET", "OPTIONS"])
def get_amp_thread(token: str = "") -> dict:
	"""The amp-list items for a thread token: the latest Communications and, with internalNotes on, Comments, oldest first.

	Each item has who, message (plain text), time, is_note and is_mine.
	"""
	actions.set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	payload, error = actions.open_conversation_token(token, "thread")
	if error:
		return error

	ctx, error = actions.load_conversation(payload, "read")
	if error:
		return error

	return {"items": actions.thread_items(ctx.doctype, ctx.docname, ctx.conv, payload["user"])}


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
@rate_limit(limit=60, seconds=60)
def post_amp_reply(token: str = "", text: str = "") -> dict:
	"""Reply to the document's sender from the email.

	An HD Ticket replies through reply_via_agent; other DocTypes send a Communication to their sender_field address.
	"""
	return actions.post_conversation(token, text, "reply")


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
@rate_limit(limit=60, seconds=60)
def post_amp_note(token: str = "", text: str = "") -> dict:
	"""Add an internal note on the document from the email; an HD Ticket gets it through new_comment."""
	return actions.post_conversation(token, text, "note")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_amp_task_status(status_token: str = "") -> dict:
	"""The live task status the email fetches on open, as one amp-list item.

	The email shows its buttons while is_waiting, else who decided or who the task moved to.
	"""
	actions.set_amp_cors_headers()

	item = {
		"is_waiting": False,
		"is_completed": False,
		"is_expired": False,
		"is_reassigned": False,
	}
	no_access = {"items": [{**item, "is_expired": True}]}

	if not status_token:
		return no_access

	try:
		from one_bpmn.processa_engine.notifications.token import verify_action_token

		payload = verify_action_token(status_token, allow_expired=True)
	except Exception:
		return no_access

	if payload.get("type") != "status":
		return no_access

	instance_name = payload.get("instance_name")
	task_id = payload.get("task_id")

	try:
		if not task_id:
			# Notice emails have no task: only the document state is shown
			state, style = actions.get_workflow_state_and_style(instance_name)
			return {"items": [{**item, "workflow_state": state, "workflow_state_style": style}]}

		task_row = frappe.db.get_value(
			"BPMN Active Task",
			{"parent": instance_name, "task_id": task_id},
			["status", "task_name", "assigned_user", "end_time", "modified"],
			as_dict=True,
		)
		if not task_row:
			return no_access

		if task_row.status == "Waiting":
			expired = bool(payload.get("expired"))
			recipient = payload.get("user")
			reassigned = bool(recipient and task_row.assigned_user and task_row.assigned_user != recipient)
			item.update(
				is_waiting=not expired and not reassigned,
				is_expired=expired,
				is_reassigned=reassigned,
			)
			if reassigned:
				item["assigned_to"] = frappe.utils.get_fullname(task_row.assigned_user)
			return {"items": [item]}

		# Task is completed: an expired token still shows who decided
		doc_name, doc_state = actions.get_context_doc_state(instance_name)
		state, style = actions.get_workflow_state_and_style(instance_name)
		time_value = task_row.end_time or task_row.modified
		log_data = frappe.db.get_value(
			"BPMN Activity Log",
			{"instance": instance_name, "task_id": task_id, "action": "Completed"},
			"data",
		)
		chosen_action = frappe.parse_json(log_data).get("action") if log_data else None
		item.update(
			is_completed=True,
			doc_name=doc_name,
			doc_state=doc_state,
			action_taken=chosen_action or task_row.task_name or _("Action"),
			completed_by=frappe.utils.get_fullname(task_row.assigned_user) if task_row.assigned_user else "",
			completed_at=frappe.utils.format_datetime(time_value, "d MMM, h:mm a") if time_value else "",
			workflow_state=state,
			workflow_state_style=style,
		)
		return {"items": [item]}
	except Exception:
		frappe.log_error(title="AMP task status failed", message=frappe.get_traceback())
		return no_access


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def download_attachment(token: str = "") -> None:
	"""Download the File a file token names, served through the File DocType, never from a request path.

	Raises PermissionError for a bad token, a token of another type, or a File not attached to the signed document.
	"""
	if not token:
		actions.attachment_denied()

	try:
		from one_bpmn.processa_engine.notifications.token import verify_action_token

		payload = verify_action_token(token, allow_expired=True)
	except Exception:
		actions.attachment_denied()

	if payload.get("type") != "file":
		actions.attachment_denied()

	doctype = payload.get("doctype")
	docname = payload.get("docname")
	file_name = payload.get("file_name")
	if not (doctype and docname and file_name):
		actions.attachment_denied()

	if payload.get("expired"):
		url = frappe.utils.get_url_to_form(doctype, docname)
		link = f'<a href="{_html.escape(url)}">{_html.escape(_("Open in ERPNext"))}</a>'
		frappe.respond_as_web_page(
			_("Link expired"),
			"<p>{0}</p><p>{1}</p>".format(_html.escape(_("This attachment link has expired.")), link),
			http_status_code=410,
			indicator_color="orange",
		)
		return

	attached = frappe.db.get_value(
		"File",
		file_name,
		["attached_to_doctype", "attached_to_name"],
		as_dict=True,
	)
	if not attached or attached.attached_to_doctype != doctype or attached.attached_to_name != docname:
		actions.attachment_denied()

	file_doc = frappe.get_doc("File", file_name)
	frappe.local.response.filename = file_doc.file_name or file_doc.name
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
def submit_comment(token: str | None = None, comment: str | None = None) -> dict:
	"""Add comment to the document a doc action token with action Comment names; returns message or error."""
	actions.set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	if not token:
		frappe.local.response.http_status_code = 403
		return {"error": _("Missing action token.")}

	try:
		from one_bpmn.processa_engine.notifications.token import verify_action_token

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
