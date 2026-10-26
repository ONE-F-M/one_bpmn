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
# Conversation endpoints (thread, reply, internal note from the email)
# ---------------------------------------------------------------------------

_THREAD_LIMIT = 10
_DEFAULT_CONVERSATION_KEY = {"reply": "Reply", "note": "Note"}


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


def _get_conversation_config(instance, task_id: str) -> dict:
	"""``notifyConversation`` of the task, as a dict (empty when absent).

	Accepts the setting as a dict or a JSON string. Understood keys:
	``key`` (action key sent to complete_task), ``completesTask`` and
	``internalNotes``.
	"""
	try:
		state = json.loads(instance.workflow_state or "{}")
		bpmn_id = state["tasks"][task_id]["task_spec"]
		spec = json.loads(instance.serialized_spec or "{}")
		cfg = spec["user_task_extensions"][bpmn_id]
	except (KeyError, TypeError, ValueError):
		return {}

	conv = (cfg or {}).get("notifyConversation")
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


def _complete_with_conversation(payload: dict, conv: dict, kind: str, text: str) -> bool:
	"""Complete the task when the conversation action completes it."""
	completes = conv.get("completesTask", conv.get("completes"))
	if not _truthy(completes):
		return False

	key = conv.get("key") or _DEFAULT_CONVERSATION_KEY[kind]
	try:
		from one_bpmn.api.instance_api import complete_task

		complete_task(
			instance_name=payload["instance_name"],
			task_id=payload["task_id"],
			data=json.dumps({"action": key, "comment": text}),
		)
		return True
	except Exception:
		# The message is already posted; do not report it as failed.
		frappe.log_error(
			title="AMP conversation: completing the task failed",
			message=frappe.get_traceback(),
		)
		return False


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

	completed = _complete_with_conversation(payload, ctx.conv, kind, text)
	return {"message": item.get("message") or text, "item": item, "completed": completed}


def _send_reply(doc, text: str, user: str) -> dict:
	"""Send ``text`` as a Communication to the document's sender_field address."""
	if doc.doctype == "HD Ticket":
		# Sends to the ticket's customer and sets the status to Replied.
		doc.reply_via_agent(message=text)
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
	``sender_field`` address. When the task's conversation action completes
	the task, ``complete_task`` runs with the conversation key and the text
	as comment.
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
			["status", "task_name", "assigned_user", "end_time", "modified"],
			as_dict=True,
		)

		if not task_row or task_row.status == "Waiting":
			return {"items": [{"is_waiting": True}]}

		# Task is completed
		doc_name, doc_state = _get_context_doc_state(instance_name)
		return {
			"items": [{
				"is_completed": True,
				"is_waiting": False,
				"doc_name": doc_name,
				"doc_state": doc_state,
				"action_taken": task_row.task_name or "Action",
				"completed_by": frappe.utils.get_fullname(task_row.assigned_user) if task_row.assigned_user else "",
				"completed_at": frappe.utils.format_datetime(
					task_row.end_time or task_row.modified, "d MMM, h:mm a"
				) if (task_row.end_time or task_row.modified) else "",
			}]
		}
	except Exception:
		return {"items": [{"is_waiting": True}]}


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

