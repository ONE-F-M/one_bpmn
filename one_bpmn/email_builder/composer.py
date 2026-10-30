"""Composer — orchestrates AMP + HTML-fallback email rendering and sending.

Ties together Stories 1–4 into two public entry points:

``compose_and_send_task_email``
	**User Task path** — called from ``notify_task_assignee`` when a BPMN
	User Task with ``notifyAssignee=true`` opens.  Renders subject /
	body from the task's notification config, builds action buttons
	(one-click for simple actions, "Open in ERPNext" links for actions
	that need confirmation or digital signature), generates HMAC tokens,
	renders AMP + HTML fallback, and sends with frappe.sendmail.

``compose_and_send_info_email``
	**Service Task path** — called from ``dispatch_email`` for
	``serviceType=send_email``.  Renders an AMP info card (content +
	"Open in ERPNext", no action buttons).  Returns the rendered AMP
	HTML string for ``dispatch_email`` to inject into the email.

Both paths reuse:
- ``one_bpmn.email_builder.renderer``   (AMP + HTML-fallback templates)
- ``one_bpmn.email_builder.email_actions`` (HMAC token enrichment)
- ``one_bpmn.utils.token``               (token generation)
"""

from __future__ import annotations

import json
import re

import frappe
from frappe import _

EMAIL_LOGO = "https://one-fm.com/files/ONEFM_Identity.png"


# ---------------------------------------------------------------------------
# User Task path
# ---------------------------------------------------------------------------


def compose_and_send_task_email(
	instance,
	user: str,
	task_name: str,
	task_id: str,
	bpmn_id: str,
	task_cfg: dict | None = None,
) -> None:
	"""Compose and send the interactive AMP email for a User Task assignment.

	Reads the task's notification config from ``task_cfg`` or, when not
	given, from ``_user_task_extensions``. Does nothing if ``notifyAssignee``
	is not ``"true"``.
	"""
	if task_cfg is None:
		task_cfg = getattr(instance, "_user_task_extensions", {}).get(bpmn_id, {})

	if task_cfg.get("notifyAssignee") != "true":
		return

	if _sends_decision_card(task_cfg):
		_send_decision_card(instance, user, task_name, task_id, bpmn_id, task_cfg)
		return

	# ── Resolve context document ──────────────────────────────────────
	doc = _get_context_doc(instance)
	jinja_ctx = _jinja_context(doc, instance)

	# ── Resolve subject + body ────────────────────────────────────────
	subject, body = _resolve_subject_body(task_cfg, jinja_ctx, task_name, instance)

	# ── Build open link ───────────────────────────────────────────────
	open_link = _build_open_link(instance)

	# ── Build action list ─────────────────────────────────────────────
	actions = _build_actions_for_email(
		task_cfg, instance, task_id, user, open_link
	)

	# ── Compose task_content ──────────────────────────────────────────
	task_content = {
		"subject": subject,
		"body": body,
		"actions": actions,
		"open_link": open_link,
		"doctype": instance.context_doctype or "",
		"name": instance.context_docname or "",
	}

	# ── Render ────────────────────────────────────────────────────────
	from one_bpmn.email_builder.renderer import render_amp, render_html_fallback

	amp_html = render_amp(task_content)
	html_body = render_html_fallback(task_content)

	# ── Send ──────────────────────────────────────────────────────────
	_send_email(
		recipients=[user],
		subject=subject,
		html_body=html_body,
		amp_html=amp_html,
		sender_account=task_cfg.get("notifyAssigneeAccount") or task_cfg.get("emailAccount", ""),
		reference_doctype=instance.context_doctype or instance.doctype,
		reference_name=instance.context_docname or instance.name,
	)


# ---------------------------------------------------------------------------
# Service Task path
# ---------------------------------------------------------------------------


def compose_and_send_info_email(
	instance,
	task_cfg: dict,
	rendered_subject: str,
	rendered_body: str,
) -> str | None:
	"""Render an AMP info card for a Service Task email.

	Returns the rendered AMP HTML string.  The caller (``dispatch_email``)
	handles the actual email sending — this function only renders the AMP
	part.

	Args:
		instance:         BPMN Process Instance document.
		task_cfg:         Service task extension config dict.
		rendered_subject: Already Jinja-rendered subject line.
		rendered_body:    Already Jinja-rendered body HTML.

	Returns:
		AMP HTML string, or ``None`` if rendering fails.
	"""
	open_link = _build_open_link(instance)

	task_content = {
		"subject": rendered_subject,
		"body": rendered_body,
		"actions": [],              # Info-only — no action buttons
		"open_link": open_link,
		"doctype": instance.context_doctype or "",
		"name": instance.context_docname or "",
	}

	try:
		from one_bpmn.email_builder.renderer import render_amp

		return render_amp(task_content)
	except Exception:
		frappe.log_error(
			title="BPMN: AMP info email render failed",
			message=frappe.get_traceback(),
		)
		return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_context_doc(instance):
	"""Load the context document, returning a frappe._dict on failure."""
	if instance.context_doctype and instance.context_docname:
		try:
			return frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			pass
	return frappe._dict()


def _jinja_context(doc, instance) -> dict:
	"""Build the Jinja template context dict."""
	return {
		"doc": doc,
		"instance": instance,
		"frappe": frappe,
	}


def _render_template(text: str, ctx: dict) -> str:
	"""Safely render a Jinja template string."""
	if not text:
		return ""
	try:
		return frappe.render_template(text, ctx)
	except Exception:
		return text  # Return raw on template error


def _resolve_subject_body(
	task_cfg: dict, jinja_ctx: dict, task_name: str, instance
) -> tuple[str, str]:
	"""Resolve the email subject and body from task config.

	Priority:
	1. Modeler fields ``notifyAssigneeSubject`` / ``notifyAssigneeBody``
	2. Inline ``notifySubject`` / ``notifyBody``
	3. Email Template (``notifyAssigneeTemplate``, or ``notifyTemplate`` on older maps) fields
	4. Default fallback
	"""
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import _decode_html_attr

	subject = task_cfg.get("notifyAssigneeSubject", "") or task_cfg.get("notifySubject", "")
	body = _decode_html_attr(task_cfg.get("notifyAssigneeBody", "")) or task_cfg.get("notifyBody", "")

	# If neither is set, try loading from the Email Template
	template_name = task_cfg.get("notifyAssigneeTemplate", "") or task_cfg.get("notifyTemplate", "")
	if template_name and (not subject or not body):
		try:
			tmpl = frappe.get_doc("Email Template", template_name)
			if not subject:
				subject = tmpl.subject or ""
			if not body:
				body = tmpl.response_ or ""
		except frappe.DoesNotExistError:
			frappe.log_error(
				title="Email Template not found",
				message=f"Task {task_name}: Email Template {template_name} does not exist",
			)

	# Render with Jinja
	subject = _render_template(subject, jinja_ctx)
	body = _render_template(body, jinja_ctx)

	# Fallback defaults
	if not subject:
		subject = _("Task: {0} — {1}").format(task_name, instance.name)
	if not body:
		body = "<p>{}</p>".format(
			_("You have been assigned the task <b>{0}</b> on <b>{1}</b>.").format(
				task_name, instance.name
			)
		)

	return subject, body


def _build_open_link(instance) -> str:
	"""Build the 'Open in ERPNext' URL for the context document."""
	base = frappe.utils.get_url()
	if instance.context_doctype and instance.context_docname:
		if instance.context_doctype == "HD Ticket":
			# Helpdesk's own portal, not the desk form. Its router forwards a
			# non-agent to /helpdesk/my-tickets/<id>, so one link serves both.
			return f"{base}/helpdesk/tickets/{instance.context_docname}"
		slug = instance.context_doctype.lower().replace(" ", "-")
		return f"{base}/app/{slug}/{instance.context_docname}"
	# Fallback: link to the BPMN instance itself
	return f"{base}/app/bpmn-process-instance/{instance.name}"


def _build_actions_for_email(
	task_cfg: dict,
	instance,
	task_id: str,
	user: str,
	open_link: str,
) -> list[dict]:
	"""Build the action list for the email template.

	Actions that require confirmation or digital signature are rendered as
	"Open in ERPNext" links.  Simple actions get HMAC tokens for one-click
	AMP form submissions.
	"""
	raw_actions = task_cfg.get("taskActions", "")
	if not raw_actions:
		return []

	# Parse the taskActions JSON (or legacy comma-separated)
	if raw_actions.strip().startswith("["):
		try:
			parsed = json.loads(raw_actions)
		except (json.JSONDecodeError, ValueError):
			parsed = []
	else:
		parsed = [
			{"action": a.strip()} for a in raw_actions.split(",") if a.strip()
		]

	if not parsed:
		return []

	link_actions = []    # rendered as "Open in ERPNext" links
	simple_actions = []  # eligible for one-click token buttons

	for i, act in enumerate(parsed):
		action_name = act.get("action", "")
		if not action_name:
			continue

		needs_confirm = act.get("confirmTransition") == "true"
		needs_sign = act.get("requireDigitalSignature") == "true"

		if needs_confirm or needs_sign:
			# Render as "Open in ERPNext" link (not one-click)
			link_actions.append({
				"label": action_name,
				"url": open_link,
				"primary": i == 0,
			})
		else:
			# Eligible for one-click AMP button
			simple_actions.append({
				"label": action_name,
				"primary": i == 0 and not link_actions,  # first overall is primary
			})

	# Generate tokens for simple actions
	enriched_simple = []
	if simple_actions and task_id:
		from one_bpmn.email_builder.email_actions import build_email_actions

		enriched_simple = build_email_actions(
			instance_name=instance.name,
			task_id=task_id,
			actions=simple_actions,
			user=user,
		)

	# Combine: link actions first, then one-click actions
	return link_actions + enriched_simple


def _send_email(
	recipients: list[str],
	subject: str,
	html_body: str,
	amp_html: str,
	sender_account: str = "",
	reference_doctype: str = "",
	reference_name: str = "",
	cc: str | None = None,
	bcc: list[str] | None = None,
) -> None:
	"""Send the email wrapped in bpmn_email.html, with the AMP part when given.

	Sets ``frappe.flags.amp_html`` so the Email Queue ``after_insert`` hook
	picks it up, and clears it afterwards so a send that writes no queue row
	cannot leak AMP into the next email of the request.
	"""
	recipients = [r for r in recipients if r != "Administrator"]
	if not recipients:
		return

	sender = None
	if sender_account:
		sender = frappe.db.get_value("Email Account", sender_account, "email_id")

	if amp_html:
		frappe.flags.amp_html = amp_html

	try:
		frappe.sendmail(
			recipients=recipients,
			sender=sender,
			subject=subject,
			cc=cc,
			bcc=bcc,
			template="bpmn_email",
			args={"header": subject, "message": html_body, "logo": EMAIL_LOGO},
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			delayed=False,
		)
	finally:
		frappe.flags.amp_html = None


# ---------------------------------------------------------------------------
# Decision card layout
# ---------------------------------------------------------------------------

DEFAULT_TOKEN_HOURS = 72
MAX_TOKEN_HOURS = 720
ACTION_ENDPOINT = "/api/method/one_bpmn.api.todo_actions.handle_amp_action"
_ACTION_CONDITION_RE = re.compile(r"""action\s*==\s*["']([^"']+)["']""")


def _sends_decision_card(task_cfg: dict) -> bool:
	"""Layout "card", or no layout on a task that has no body and no template."""
	layout = task_cfg.get("notifyLayout") or ""
	if layout:
		return layout == "card"
	has_body = task_cfg.get("notifyAssigneeBody") or task_cfg.get("notifyBody")
	has_template = task_cfg.get("notifyAssigneeTemplate") or task_cfg.get("notifyTemplate")
	return not has_body and not has_template


def _send_decision_card(
	instance, user: str, task_name: str, task_id: str, bpmn_id: str, task_cfg: dict
) -> None:
	from one_bpmn.email_builder.renderer import render_layout_amp, render_layout_html

	ctx = _build_layout_context(instance, user, task_name, task_id, bpmn_id, task_cfg)
	_send_email(
		recipients=[user],
		subject=ctx["subject_line"],
		html_body=render_layout_html(ctx),
		amp_html=render_layout_amp(ctx),
		sender_account=task_cfg.get("notifyAssigneeAccount") or task_cfg.get("emailAccount", ""),
		reference_doctype=instance.context_doctype or instance.doctype,
		reference_name=instance.context_docname or instance.name,
	)


def _build_layout_context(
	instance, user: str, task_name: str, task_id: str, bpmn_id: str, task_cfg: dict
) -> dict:
	"""Everything decision_card.html reads, in both languages."""
	from one_bpmn.email_builder.fields import (
		build_attachment_links,
		build_field_rows,
		build_kick,
		default_fact_fields,
	)
	from one_bpmn.utils.token import generate_status_token

	doc = _get_context_doc(instance)
	jinja_ctx = _jinja_context(doc, instance)
	hours = _token_hours(task_cfg.get("notifyTokenHours"))
	doctype = instance.context_doctype or ""

	subject_en = _render_template(task_cfg.get("notifyAssigneeSubject", ""), jinja_ctx) or task_name
	subject_ar = _render_template(task_cfg.get("notifySubjectAr", ""), jinja_ctx)
	question_en = _render_template(task_cfg.get("notifyQuestionEn", ""), jinja_ctx) or task_name
	question_ar = _render_template(task_cfg.get("notifyQuestionAr", ""), jinja_ctx) or _arabic(task_name)

	has_doc = bool(getattr(doc, "meta", None))
	facts = json.loads(task_cfg.get("notifyFacts") or "[]") or (
		default_fact_fields(doctype) if has_doc else []
	)
	details = json.loads(task_cfg.get("notifyDetails") or "[]")
	attachments = []
	if has_doc and task_cfg.get("notifyAttachments") == "true":
		attachments = [{"name": a["file_name"], "url": a["url"]} for a in build_attachment_links(doc, hours)]

	status_token = generate_status_token(instance.name, task_id, expiry_hours=hours, user=user)
	site_url = frappe.utils.get_url()
	open_link = _build_open_link(instance)
	return {
		"layout": "decision_card",
		"subject_line": f"{subject_en} || {subject_ar}" if subject_ar else subject_en,
		"kick": build_kick(doctype or instance.doctype, task_name),
		"question": {"en": question_en, "ar": question_ar},
		"facts": build_field_rows(doc, facts) if has_doc else [],
		"details": build_field_rows(doc, details) if has_doc else [],
		"attachments": attachments,
		"status_url": f"{site_url}/api/method/one_bpmn.api.todo_actions.get_amp_task_status?status_token={status_token}",
		"open_link": open_link,
		"action_endpoint": f"{site_url}{ACTION_ENDPOINT}",
		"actions": _build_layout_actions(instance, user, task_id, bpmn_id, task_cfg, hours, open_link),
	}


def _build_layout_actions(
	instance, user: str, task_id: str, bpmn_id: str, task_cfg: dict, hours: int, open_link: str
) -> list[dict]:
	"""Task Actions in order: labels in both languages, primary, confirm, sign, the state each leads to, a token."""
	from one_bpmn.utils.token import generate_action_token

	try:
		task_actions = json.loads(task_cfg.get("taskActions") or "[]")
	except ValueError:
		task_actions = [
			{"action": a.strip()} for a in task_cfg.get("taskActions", "").split(",") if a.strip()
		]
	settings = json.loads(task_cfg.get("notifyActions") or "{}")
	names = [a.get("action") for a in task_actions if a.get("action")]
	primary = next((n for n in names if settings.get(n, {}).get("primary")), names[0] if names else "")
	states = _action_states(instance, bpmn_id, names)

	actions = []
	for act in task_actions:
		name = act.get("action")
		if not name:
			continue
		sign = act.get("requireDigitalSignature") == "true"
		state, style = states.get(name, ("", ""))
		label = {"en": name, "ar": _arabic(name)}
		reason = settings.get(name, {})
		actions.append(
			{
				"key": frappe.scrub(name),
				"label": label,
				"reason": bool(reason.get("reason")) and not sign,
				"reason_question": {
					"en": _("Reason for {0}", lang="en").format(name),
					"ar": _("Reason for {0}", lang="ar").format(label["ar"]),
				},
				"chips": [{"en": en, "ar": ar or en} for en, ar in reason.get("chips") or []],
				"primary": name == primary,
				"confirm": act.get("confirmTransition") == "true",
				"sign": sign,
				"state": state,
				"style": style,
				"url": open_link if sign else "",
				"token": ""
				if sign
				else generate_action_token(instance.name, task_id, name, user, expiry_hours=hours),
			}
		)
	return actions


def _action_states(instance, bpmn_id: str, action_names: list[str]) -> dict:
	"""{action: (workflow state, Workflow State style)} for actions whose branch reaches an Apply Workflow task.

	Reads the gateway right after the user task: a branch with condition action == "Name",
	else the gateway's default branch, followed to the first apply_workflow service task.
	"""
	import xml.etree.ElementTree as ET

	model = (
		frappe.db.get_value("BPMN Process Instance", instance.name, "process_model")
		if instance.name
		else None
	)
	xml = frappe.db.get_value("BPMN Process Model", model, "bpmn_xml") if model else None
	if not xml:
		return {}

	elements = {el.get("id"): el for el in ET.fromstring(xml).iter() if el.get("id")}
	flows = [el for el in elements.values() if el.tag.endswith("sequenceFlow")]

	def outgoing(node_id):
		return [f for f in flows if f.get("sourceRef") == node_id]

	after_task = outgoing(bpmn_id)
	if len(after_task) != 1:
		return {}
	gateway = elements.get(after_task[0].get("targetRef"))
	if gateway is None or not gateway.tag.endswith("Gateway"):
		return {}

	branches = {}
	for flow in outgoing(gateway.get("id")):
		condition = next((c.text or "" for c in flow if c.tag.endswith("conditionExpression")), "")
		match = _ACTION_CONDITION_RE.search(condition)
		if match:
			branches[match.group(1)] = flow.get("targetRef")
	default_target = (
		elements.get(gateway.get("default"), {}).get("targetRef") if gateway.get("default") else None
	)

	states = {}
	for name in action_names:
		state = _first_workflow_state(elements, outgoing, branches.get(name) or default_target)
		if state:
			states[name] = (state, frappe.db.get_value("Workflow State", state, "style") or "")
	return states


def _first_workflow_state(elements: dict, outgoing, node_id: str | None, steps: int = 10) -> str:
	"""Follow single-path nodes from node_id to the first apply_workflow service task's workflowState."""
	for _step in range(steps):
		node = elements.get(node_id)
		if node is None:
			return ""
		if node.tag.endswith("serviceTask"):
			attrs = {key.split("}")[-1]: value for key, value in node.attrib.items()}
			if attrs.get("serviceType") == "apply_workflow":
				return attrs.get("workflowState", "")
		next_flows = outgoing(node_id)
		if len(next_flows) != 1 or node.tag.endswith(("userTask", "Gateway")):
			return ""
		node_id = next_flows[0].get("targetRef")
	return ""


def _token_hours(raw) -> int:
	hours = frappe.utils.cint(raw)
	return hours if 1 <= hours <= MAX_TOKEN_HOURS else DEFAULT_TOKEN_HOURS


def _arabic(text: str) -> str:
	"""Frappe's Arabic for text, else the cached machine translation, else text."""
	from one_bpmn.utils.translation import TranslationError, translate_cached

	translated = _(text, lang="ar")
	if translated != text:
		return translated
	try:
		return translate_cached(text)
	except TranslationError:
		return text
