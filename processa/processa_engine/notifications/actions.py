"""Logic behind the AMP email callbacks: CORS headers, action tokens, reasons, receipts and the conversation thread."""

from __future__ import annotations

import html as _html
import json
import re

import frappe
from frappe import _

from processa.processa_engine.notifications.token import generate_action_token


def build_email_actions(
	instance_name: str,
	task_id: str,
	actions: list[dict],
	user: str,
	expiry_hours: int = 720,
) -> list[dict]:
	"""Copies of the action dicts, each with an HMAC token for the AMP email.

	The default 720 hours keeps the button working when the email is opened days later.
	"""
	enriched = []
	for action in actions:
		action_name = action.get("label", "")
		token = generate_action_token(
			instance_name=instance_name,
			task_id=task_id,
			action=action_name,
			user=user,
			expiry_hours=expiry_hours,
		)
		enriched.append({
			**action,
			"token": token,
			"instance_name": instance_name,
			"task_id": task_id,
			"action_name": action_name,
		})
	return enriched


_AMP_ALLOWED_ORIGINS = frozenset({
	"https://mail.google.com",
	"https://amp.gmail.dev",
})


def set_amp_cors_headers() -> None:
	"""Store the AMP-only CORS headers in frappe.flags for apply_amp_headers; Frappe's allow_cors sets the rest."""
	extra = {}

	extra["Access-Control-Expose-Headers"] = "AMP-Access-Control-Allow-Source-Origin, AMP-Email-Allow-Sender"

	source_origin = frappe.request.args.get("__amp_source_origin", "")
	if source_origin:
		extra["AMP-Access-Control-Allow-Source-Origin"] = source_origin

	sender = frappe.request.headers.get("AMP-Email-Sender", "")
	if sender:
		extra["AMP-Email-Allow-Sender"] = sender

	frappe.flags._amp_extra_headers = extra


def apply_amp_headers(response, **kwargs):
	"""after_request hook: add the stored AMP CORS headers to the response."""
	extra = getattr(frappe.flags, "_amp_extra_headers", None)
	if extra:
		for key, value in extra.items():
			response.headers[key] = value


def save_reason(
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


_THREAD_LIMIT = 10


def _truthy(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes", "on")
	return bool(value)


def plain_text(value: str | None) -> str:
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


def open_conversation_token(token: str | None, kind: str):
	"""Verify a conversation token of the given kind and act as its user: (payload, None) or (None, error_response).

	Nothing is read or written before the token is verified and its type matched to the endpoint.
	"""
	if not token:
		return None, _conversation_error(403, _("Missing action token."))

	try:
		from processa.processa_engine.notifications.token import verify_action_token

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
	"""Same rule as Helpdesk's is_agent, read from roles and HD Agent so Helpdesk need not be installed."""
	if user == "Administrator" or {"Agent", "Agent Manager"} & set(frappe.get_roles(user)):
		return True
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
		"message": plain_text(row.get("content")),
		"time": _format_time(row.get("creation")),
		"is_note": False,
	}


def _note_item(row, author_field: str) -> dict:
	author = row.get(author_field) or row.get("owner") or ""
	return {
		"who": frappe.utils.get_fullname(author) if author else "",
		"message": plain_text(row.get("content")),
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


def load_conversation(payload: dict, ptype: str):
	"""Resolve instance, context document, config and access: (ctx, None) or (None, error_response)."""
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


def post_conversation(token: str | None, text: str | None, kind: str) -> dict:
	"""Shared body of the post_amp_reply and post_amp_note endpoints."""
	set_amp_cors_headers()

	if frappe.request.method == "OPTIONS":
		frappe.response["type"] = "text"
		frappe.response["message"] = ""
		return {}

	payload, error = open_conversation_token(token, kind)
	if error:
		return error

	text = (text or "").strip()
	if not text:
		return _conversation_error(400, _("Write a message first."))

	ctx, error = load_conversation(payload, "write")
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
		# Sends to the ticket's customer and sets the status to Replied
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



def thread_items(doctype: str, docname: str, conv: dict, user: str) -> list[dict]:
	"""The latest Communications and, with internal notes on, Comments, oldest first; is_mine marks user's own."""
	entries = []
	comms = frappe.get_all(
		"Communication",
		filters={
			"reference_doctype": doctype,
			"reference_name": docname,
			"communication_type": "Communication",
		},
		fields=["name", "sender", "sender_full_name", "owner", "content", "creation"],
		order_by="creation desc",
		limit=_THREAD_LIMIT,
	)
	entries += [(row, _communication_item(row)) for row in comms]

	if _truthy(conv.get("internalNotes")):
		comment_dt, filters, author_field = _comment_source(doctype, docname)
		notes = frappe.get_all(
			comment_dt,
			filters=filters,
			fields=["name", author_field, "owner", "content", "creation"],
			order_by="creation desc",
			limit=_THREAD_LIMIT,
		)
		entries += [(row, _note_item(row, author_field)) for row in notes]

	entries.sort(key=lambda entry: str(entry[0].creation))
	return [{**item, "is_mine": row.owner == user} for row, item in entries]


def get_workflow_state_and_style(instance_name: str) -> tuple[str, str]:
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


def receipt(instance_name: str, doctype: str, docname: str, action: str) -> dict:
	"""The state the document reached and "<DocType> <name> is now <state>.", else "You chose <action>.", in both languages."""
	from processa.processa_engine.notifications.composer import arabic_text

	state, style = get_workflow_state_and_style(instance_name)
	completed_at = frappe.utils.format_datetime(frappe.utils.now_datetime(), "d MMM, h:mm a")
	if not state:
		action_ar = arabic_text(action)
		return {
			"state": "",
			"state_label": {"en": action, "ar": action_ar},
			"state_style": "",
			"receipt": {
				"en": _("You chose {0}.", lang="en").format(action),
				"ar": _("You chose {0}.", lang="ar").format(action_ar),
			},
			"completed_at": completed_at,
		}
	return {
		"state": state,
		"state_label": {"en": state, "ar": _(state, lang="ar")},
		"state_style": style,
		"receipt": {
			"en": _("{0} {1} is now {2}.", lang="en").format(doctype, docname, state),
			"ar": _("{0} {1} is now {2}.", lang="ar").format(arabic_text(doctype), docname, _(state, lang="ar")),
		},
		"completed_at": completed_at,
	}


def get_context_doc_state(instance_name: str) -> tuple[str, str]:
	"""(docname, state) of the instance's context document: workflow_state, else status, else empty.

	Both are empty when the instance has no context document.
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


def attachment_denied():
	raise frappe.PermissionError(_("This attachment link is not valid."))
