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

import html as _html
import json
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit


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
	extra["Access-Control-Expose-Headers"] = "AMP-Access-Control-Allow-Source-Origin, AMP-Email-Allow-Sender"

	# Echo back the __amp_source_origin query param
	source_origin = frappe.request.args.get("__amp_source_origin", "")
	if source_origin:
		extra["AMP-Access-Control-Allow-Source-Origin"] = source_origin

	# Echo back the AMP-Email-Sender request header (current Gmail spec)
	sender = frappe.request.headers.get("AMP-Email-Sender", "")
	if sender:
		extra["AMP-Email-Allow-Sender"] = sender

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
def handle_amp_action(
	token: str | None = None,
	comment: str | None = None,
	reason_chip: str | None = None,
	reason_text: str | None = None,
	reason_lang: str | None = None,
) -> dict:
	"""Process an action submitted from an AMP email button.

	Args:
		token: HMAC-signed token from :func:`~one_bpmn.utils.token.generate_action_token`.
		comment: Optional comment text submitted with the action.
		reason_chip: Index of the reason chip picked in the email's reason panel.
		reason_text: Reason typed in the reason panel.
		reason_lang: Language the reader had the email in; the reason panel always posts it.

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

	# A token with a "type" (conversation / status) is not an action token.
	if payload.get("type"):
		frappe.local.response.http_status_code = 403
		return {"error": _("This link cannot be used to action a task.")}

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

		saved_reason = None
		if reason_lang is not None:
			saved_reason = _save_reason(instance_name, task_id, action, reason_chip, reason_text, reason_lang)
		if saved_reason:
			task_data["comment"] = saved_reason["reason"]

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
			**_receipt(instance_name, ctx_dt),
			"reason_saved": saved_reason["saved"] if saved_reason else {"en": "", "ar": ""},
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


def _save_reason(
	instance_name: str, task_id: str, action: str, reason_chip: str | None, reason_text: str | None, lang: str
) -> dict | None:
	"""Write the reason the action asks for to its field, as the token user; None when it asks for none."""
	instance = _get_instance_context(instance_name)
	task_cfg = _get_task_config(instance, task_id)
	settings = json.loads(task_cfg.get("notifyActions") or "{}").get(action) or {}
	if not settings.get("reason"):
		return None

	lang = lang if lang in ("en", "ar") else "en"
	chips = settings.get("chips") or []
	chip = chips[int(reason_chip)] if (reason_chip or "").isdigit() and int(reason_chip) < len(chips) else None
	chip_text = ((chip[1] if lang == "ar" else "") or chip[0]) if chip else ""
	reason = "\n".join(text for text in (chip_text, (reason_text or "").strip()) if text)
	if not reason:
		frappe.throw(_("A reason is required for {0}.").format(action))

	doctype = instance.context_doctype
	fieldname = settings.get("reasonField") or ""
	df = frappe.get_meta(doctype).get_field(fieldname) if doctype and fieldname else None
	if not df:
		message = _("The reason field {0} is not on {1}.").format(fieldname, doctype)
		frappe.log_error(title="AMP: reason field missing", message=message)
		frappe.throw(message)

	doc = frappe.get_doc(doctype, instance.context_docname)
	doc.check_permission("write")
	doc.db_set(fieldname, reason)
	return {
		"reason": reason,
		"saved": {
			"en": _("Reason saved to {0}", lang="en").format(df.label),
			"ar": _("Reason saved to {0}", lang="ar").format(_(df.label, lang="ar")),
		},
	}


# ---------------------------------------------------------------------------
# Conversation endpoints (thread, reply, internal note from the email)
# ---------------------------------------------------------------------------

_THREAD_LIMIT = 10


def _truthy(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes", "on")
	return bool(value)


def _plain_text(value: str | None) -> str:
	"""HTML to plain text for the thread view."""
	text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value or "")
	text = re.sub(r"<[^>]*>", "", text)
	text = _html.unescape(text)
	text = re.sub(r"[ \t]+", " ", text)
	text = re.sub(r"\n\s*\n+", "\n\n", text)
	return text.strip()


def _format_time(value) -> str:
	return frappe.utils.format_datetime(value, "d MMM, h:mm a") if value else ""


def _conversation_error(status: int, message: str) -> dict:
	frappe.local.response.http_status_code = status
	return {"error": message}


def _open_conversation_token(token: str | None, kind: str):
	"""Verify a conversation token of the given kind and act as its user.

	Returns ``(payload, None)`` on success or ``(None, error_response)``.
	The token is the only trust anchor: nothing is read or written before
	it has been verified and its type matched to the endpoint.
	"""
	if not token:
		return None, _conversation_error(403, _("Missing action token."))

	try:
		from one_bpmn.utils.token import verify_action_token

		payload = verify_action_token(token)
	except frappe.AuthenticationError:
		return None, _conversation_error(403, _("Invalid or tampered token."))
	except frappe.ValidationError as e:
		return None, _conversation_error(403, str(e))
	except Exception:
		return None, _conversation_error(403, _("Invalid or tampered token."))

	if payload.get("type") != kind:
		return None, _conversation_error(403, _("This link cannot be used for this request."))

	frappe.set_user(payload["user"])
	return payload, None


def _get_instance_context(instance_name: str):
	"""Context document, serialized spec and workflow state of an instance."""
	return frappe.db.get_value(
		"BPMN Process Instance",
		instance_name,
		["context_doctype", "context_docname", "serialized_spec", "workflow_state"],
		as_dict=True,
	)


def _get_task_config(instance, task_id: str) -> dict:
	"""The user task extensions of the task's BPMN element, as compiled (empty when absent)."""
	try:
		state = json.loads(instance.workflow_state or "{}")
		bpmn_id = state["tasks"][task_id]["task_spec"]
		spec = json.loads(instance.serialized_spec or "{}")
		return spec["user_task_extensions"][bpmn_id] or {}
	except (KeyError, TypeError, ValueError):
		return {}


def _get_conversation_config(instance, task_id: str) -> dict:
	"""``notifyConversation`` of the task, as a dict (empty when absent).

	Saved as ``{actions: [{key, label}], internalNotes, canned}``, as a dict or a JSON string.
	"""
	conv = _get_task_config(instance, task_id).get("notifyConversation")
	if isinstance(conv, str):
		try:
			conv = json.loads(conv)
		except ValueError:
			conv = {}
	return conv if isinstance(conv, dict) else {}


def _is_helpdesk_agent(user: str) -> bool:
	try:
		from helpdesk.utils import is_agent

		return bool(is_agent(user))
	except Exception:
		return bool(frappe.db.exists("HD Agent", user))


def _check_conversation_access(doctype: str, docname: str, ptype: str) -> None:
	"""Raise ``frappe.PermissionError`` unless the session user may act."""
	if doctype == "HD Ticket" and not _is_helpdesk_agent(frappe.session.user):
		raise frappe.PermissionError(_("Only Helpdesk agents can use the conversation."))
	frappe.get_doc(doctype, docname).check_permission(ptype)


def _comment_source(doctype: str, docname: str) -> tuple[str, dict, str]:
	"""(comment doctype, filters, author field) for the document's notes."""
	if doctype == "HD Ticket":
		return "HD Ticket Comment", {"reference_ticket": docname}, "commented_by"
	return (
		"Comment",
		{"reference_doctype": doctype, "reference_name": docname, "comment_type": "Comment"},
		"comment_email",
	)


def _communication_item(row) -> dict:
	return {
		"who": row.get("sender_full_name") or row.get("sender") or "",
		"message": _plain_text(row.get("content")),
		"time": _format_time(row.get("creation")),
		"is_note": False,
	}


def _note_item(row, author_field: str) -> dict:
	author = row.get(author_field) or row.get("owner") or ""
	return {
		"who": frappe.utils.get_fullname(author) if author else "",
		"message": _plain_text(row.get("content")),
		"time": _format_time(row.get("creation")),
		"is_note": True,
	}


def _latest_communication(doctype: str, docname: str, user: str) -> dict:
	rows = frappe.get_all(
		"Communication",
		filters={
			"reference_doctype": doctype,
			"reference_name": docname,
			"communication_type": "Communication",
			"owner": user,
		},
		fields=["name", "sender", "sender_full_name", "content", "creation"],
		order_by="creation desc",
		limit=1,
	)
	return _communication_item(rows[0]) if rows else {}


def _latest_note(doctype: str, docname: str, user: str) -> dict:
	comment_dt, filters, author_field = _comment_source(doctype, docname)
	rows = frappe.get_all(
		comment_dt,
		filters={**filters, "owner": user},
		fields=["name", author_field, "content", "creation"],
		order_by="creation desc",
		limit=1,
	)
	return _note_item(rows[0], author_field) if rows else {}


def _load_conversation(payload: dict, ptype: str):
	"""Resolve instance, context document, config and access.

	Returns ``(ctx, None)`` or ``(None, error_response)``.
	"""
	instance = _get_instance_context(payload["instance_name"])
	if not instance or not instance.context_doctype or not instance.context_docname:
		return None, _conversation_error(404, _("This conversation is no longer available."))

	doctype, docname = instance.context_doctype, instance.context_docname
	try:
		_check_conversation_access(doctype, docname, ptype)
	except frappe.PermissionError as e:
		return None, _conversation_error(403, _("Permission denied: {0}").format(str(e)))
	except frappe.DoesNotExistError:
		return None, _conversation_error(404, _("This conversation is no longer available."))

	conv = _get_conversation_config(instance, payload["task_id"])
	return frappe._dict(doctype=doctype, docname=docname, conv=conv), None


def _handled_by_message(instance_name: str, task_id: str) -> str | None:
	"""None while the task is Waiting, else a line saying who handled it."""
	row = frappe.db.get_value(
		"BPMN Active Task",
		{"parent": instance_name, "task_id": task_id},
		["status", "assigned_user"],
		as_dict=True,
	)
	if row and row.status == "Waiting":
		return None
	if row and row.assigned_user:
		return _("This task was already handled by {0}.").format(
			frappe.utils.get_fullname(row.assigned_user)
		)
	return _("This task was already handled by someone else.")


def _post_conversation(token: str | None, text: str | None, kind: str) -> dict:
	"""Shared body of :func:`post_amp_reply` and :func:`post_amp_note`."""
	_set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	payload, error = _open_conversation_token(token, kind)
	if error:
		return error

	text = (text or "").strip()
	if not text:
		return _conversation_error(400, _("Write a message first."))

	ctx, error = _load_conversation(payload, "write")
	if error:
		return error

	handled = _handled_by_message(payload["instance_name"], payload["task_id"])
	if handled:
		return {"message": handled, "handled": True}

	user = payload["user"]
	try:
		doc = frappe.get_doc(ctx.doctype, ctx.docname)
		if kind == "reply":
			item = _send_reply(doc, text, user)
		else:
			item = _add_note(doc, text, user)
	except frappe.PermissionError as e:
		return _conversation_error(403, _("Permission denied: {0}").format(str(e)))
	except frappe.ValidationError as e:
		return _conversation_error(400, str(e))
	except Exception:
		frappe.log_error(
			title=f"AMP conversation {kind} failed",
			message=frappe.get_traceback(),
		)
		return _conversation_error(500, _("An error occurred. Please try in ERPNext."))

	return {"message": item.get("message") or text, "item": item}


def _send_reply(doc, text: str, user: str) -> dict:
	"""Send ``text`` as a Communication to the document's sender_field address."""
	if doc.doctype == "HD Ticket":
		# Sends to the ticket's customer and sets the status to Replied.
		doc.reply_via_agent(message=text, to=doc.raised_by)
	else:
		sender_field = frappe.get_meta(doc.doctype).sender_field
		recipient = doc.get(sender_field) if sender_field else None
		if not recipient:
			raise frappe.ValidationError(_("There is no address on this document to reply to."))
		from frappe.core.doctype.communication.email import make

		make(
			doctype=doc.doctype,
			name=doc.name,
			content=text,
			subject=_("Re: {0}").format(doc.name),
			sender=user,
			recipients=recipient,
			communication_medium="Email",
			send_email=True,
		)
	return _latest_communication(doc.doctype, doc.name, user)


def _add_note(doc, text: str, user: str) -> dict:
	"""Add ``text`` as an internal Comment on the document."""
	if doc.doctype == "HD Ticket":
		doc.new_comment(content=text)
	else:
		doc.add_comment("Comment", text)
	return _latest_note(doc.doctype, doc.name, user)


@frappe.whitelist(allow_guest=True, methods=["GET", "OPTIONS"])
def get_amp_thread(token: str = "") -> dict:
	"""Return the latest conversation on the task's document for an AMP amp-list.

	Args:
		token: HMAC-signed token from
			:func:`~one_bpmn.utils.token.generate_conversation_token` (kind ``thread``).

	Returns:
		``{"items": [...]}``: the latest 10 Communications (``is_note`` false)
		and, when the task's ``internalNotes`` setting is on, the document's
		Comments (``is_note`` true), oldest first. Each item has ``who``,
		``message`` (plain text), ``time`` and ``is_note``.
	"""
	_set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	payload, error = _open_conversation_token(token, "thread")
	if error:
		return error

	ctx, error = _load_conversation(payload, "read")
	if error:
		return error

	entries = []
	comms = frappe.get_all(
		"Communication",
		filters={
			"reference_doctype": ctx.doctype,
			"reference_name": ctx.docname,
			"communication_type": "Communication",
		},
		fields=["name", "sender", "sender_full_name", "content", "creation"],
		order_by="creation desc",
		limit=_THREAD_LIMIT,
	)
	entries += [(row.creation, _communication_item(row)) for row in comms]

	if _truthy(ctx.conv.get("internalNotes")):
		comment_dt, filters, author_field = _comment_source(ctx.doctype, ctx.docname)
		notes = frappe.get_all(
			comment_dt,
			filters=filters,
			fields=["name", author_field, "owner", "content", "creation"],
			order_by="creation desc",
			limit=_THREAD_LIMIT,
		)
		entries += [(row.creation, _note_item(row, author_field)) for row in notes]

	entries.sort(key=lambda entry: str(entry[0]))
	return {"items": [item for _created, item in entries]}


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
@rate_limit(limit=60, seconds=60)
def post_amp_reply(token: str = "", text: str = "") -> dict:
	"""Reply to the document's sender from the email.

	For HD Ticket this goes through ``HD Ticket.reply_via_agent`` (status
	becomes Replied); other DocTypes get a Communication to their
	``sender_field`` address. When a Task Action is picked for replies,
	``complete_task`` runs with that action and the text as comment.
	"""
	return _post_conversation(token, text, "reply")


@frappe.whitelist(allow_guest=True, methods=["POST", "OPTIONS"])
@rate_limit(limit=60, seconds=60)
def post_amp_note(token: str = "", text: str = "") -> dict:
	"""Add an internal note (Comment) on the document from the email.

	For HD Ticket this goes through ``HD Ticket.new_comment``. Completion
	behaves as in :func:`post_amp_reply`.
	"""
	return _post_conversation(token, text, "note")


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
		with keys: ``is_waiting``, ``is_completed``, ``is_expired``,
		``is_reassigned``, ``assigned_to``, ``action_taken``, ``completed_by``,
		``completed_at``, ``workflow_state``, ``workflow_state_style``.
	"""
	_set_amp_cors_headers()

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
		from one_bpmn.utils.token import verify_action_token

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
			state, style = _get_workflow_state_and_style(instance_name)
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
		doc_name, doc_state = _get_context_doc_state(instance_name)
		state, style = _get_workflow_state_and_style(instance_name)
		time_value = task_row.end_time or task_row.modified
		item.update(
			is_completed=True,
			doc_name=doc_name,
			doc_state=doc_state,
			action_taken=task_row.task_name or _("Action"),
			completed_by=frappe.utils.get_fullname(task_row.assigned_user) if task_row.assigned_user else "",
			completed_at=frappe.utils.format_datetime(time_value, "d MMM, h:mm a") if time_value else "",
			workflow_state=state,
			workflow_state_style=style,
		)
		return {"items": [item]}
	except Exception:
		frappe.log_error(title="AMP task status failed", message=frappe.get_traceback())
		return no_access


def _get_workflow_state_and_style(instance_name: str) -> tuple[str, str]:
	"""Return (workflow state, Workflow State style) of the instance's context document.

	Both are empty when the instance has no context document or its DocType has no workflow.
	"""
	from frappe.model.workflow import get_workflow_name, get_workflow_state_field

	ctx = frappe.db.get_value(
		"BPMN Process Instance",
		instance_name,
		["context_doctype", "context_docname"],
		as_dict=True,
	)
	if not ctx or not ctx.context_doctype or not ctx.context_docname:
		return "", ""

	workflow_name = get_workflow_name(ctx.context_doctype)
	if not workflow_name:
		return "", ""

	state_field = get_workflow_state_field(workflow_name)
	state = frappe.db.get_value(ctx.context_doctype, ctx.context_docname, state_field) or ""
	if not state:
		return "", ""

	style = frappe.db.get_value("Workflow State", state, "style") or ""
	return str(state), str(style)


def _receipt(instance_name: str, doctype: str) -> dict:
	"""The state the document reached, its style, and "<DocType> is now <state>" in both languages."""
	state, style = _get_workflow_state_and_style(instance_name)
	if not state:
		return {"state": "", "state_label": {"en": "", "ar": ""}, "state_style": "", "receipt": {"en": "", "ar": ""}, "completed_at": ""}
	return {
		"state": state,
		"state_label": {"en": state, "ar": _(state, lang="ar")},
		"state_style": style,
		"receipt": {
			"en": _("{0} is now {1}", lang="en").format(doctype, state),
			"ar": _("{0} is now {1}", lang="ar").format(_(doctype, lang="ar"), _(state, lang="ar")),
		},
		"completed_at": frappe.utils.format_datetime(frappe.utils.now_datetime(), "d MMM, h:mm a"),
	}


def _get_context_doc_state(instance_name: str) -> tuple[str, str]:
	"""Return (docname, current state) of the instance's context document.

	State is ``workflow_state`` when the DocType has one, else ``status``,
	else empty. Empty strings when the instance has no context document.
	"""
	ctx = frappe.db.get_value(
		"BPMN Process Instance",
		instance_name,
		["context_doctype", "context_docname"],
		as_dict=True,
	)
	if not ctx or not ctx.context_doctype or not ctx.context_docname:
		return "", ""

	meta = frappe.get_meta(ctx.context_doctype)
	field = next((f for f in ("workflow_state", "status") if meta.has_field(f)), None)
	if not field:
		return ctx.context_docname, ""

	state = frappe.db.get_value(ctx.context_doctype, ctx.context_docname, field) or ""
	return ctx.context_docname, str(state)


# ---------------------------------------------------------------------------
# Signed attachment download
# ---------------------------------------------------------------------------


def _attachment_denied():
	raise frappe.PermissionError(_("This attachment link is not valid."))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def download_attachment(token: str = "") -> None:
	"""Download a file attached to a document, from a signed email link.

	The signed token is the only trust anchor: the File is looked up by the
	signed name and served through the File DocType, never from a request path.

	Args:
		token: HMAC-signed token from :func:`~one_bpmn.utils.token.generate_file_token`.

	Raises:
		frappe.PermissionError: Tampered or malformed token, a token of another
			type, or a File no longer attached to the signed document.
	"""
	if not token:
		_attachment_denied()

	try:
		from one_bpmn.utils.token import verify_action_token

		payload = verify_action_token(token, allow_expired=True)
	except Exception:
		_attachment_denied()

	if payload.get("type") != "file":
		_attachment_denied()

	doctype = payload.get("doctype")
	docname = payload.get("docname")
	file_name = payload.get("file_name")
	if not (doctype and docname and file_name):
		_attachment_denied()

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
		_attachment_denied()

	file_doc = frappe.get_doc("File", file_name)
	frappe.local.response.filename = file_doc.file_name or file_doc.name
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"

