"""Composer — orchestrates AMP + HTML-fallback email rendering and sending.

Ties together Stories 1–4 into two public entry points:

``compose_and_send_task_email``
	**User Task path** — called from ``add_frappe_assignment`` when a BPMN
	User Task with ``notifyAssignee=true`` is assigned.  Renders subject /
	body from the task's notification config, builds action buttons
	(one-click for simple actions, "Open in ERPNext" links for actions
	that need confirmation or digital signature), generates HMAC tokens,
	renders AMP + HTML fallback, and sends via the One-FM email pipeline.

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

import frappe
from frappe import _


# ---------------------------------------------------------------------------
# User Task path
# ---------------------------------------------------------------------------


def compose_and_send_task_email(
	instance,
	user: str,
	task_name: str,
	task_id: str,
	bpmn_id: str,
) -> None:
	"""Compose and send the interactive AMP email for a User Task assignment.

	Reads the task's notification config from ``_user_task_extensions``,
	renders the email, and sends it.  Does nothing if ``notifyAssignee``
	is not ``"true"``.

	Args:
		instance:  BPMN Process Instance document.
		user:      Assignee email address.
		task_name: Human-readable task name.
		task_id:   SpiffWorkflow task UUID (for HMAC tokens).
		bpmn_id:   BPMN element ID (for extension config lookup).
	"""
	# ── Read task config ──────────────────────────────────────────────
	task_cfg = getattr(instance, "_user_task_extensions", {}).get(bpmn_id, {})

	if task_cfg.get("notifyAssignee") != "true":
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
		sender_account=task_cfg.get("emailAccount", ""),
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
	1. Inline ``notifySubject`` / ``notifyBody`` (always win if non-empty)
	2. Email Template (``notifyTemplate``) fields
	3. Default fallback
	"""
	subject = task_cfg.get("notifySubject", "")
	body = task_cfg.get("notifyBody", "")

	# If neither is set, try loading from the Email Template
	template_name = task_cfg.get("notifyTemplate", "")
	if template_name and (not subject or not body):
		try:
			tmpl = frappe.get_doc("Email Template", template_name)
			if not subject:
				subject = tmpl.subject or ""
			if not body:
				body = tmpl.response or ""
		except Exception:
			pass

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
) -> None:
	"""Send the email via the One-FM pipeline with AMP injection.

	Sets ``frappe.flags.amp_html`` so the Email Queue ``before_insert``
	hook (Story 1) picks it up and stores it on the queue row.
	"""
	# Resolve sender from Email Account if configured
	sender = None
	if sender_account:
		sender = frappe.db.get_value("Email Account", sender_account, "email_id")

	# Set AMP flag before sending — picked up by Email Queue hook
	if amp_html:
		frappe.flags.amp_html = amp_html

	try:
		from one_fm.processor import sendemail as onefm_sendemail

		onefm_sendemail(
			recipients=recipients,
			subject=subject,
			sender=sender,
			header=[subject],
			message=html_body,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
	except ImportError:
		frappe.sendmail(
			recipients=recipients,
			sender=sender,
			subject=subject,
			message=html_body,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			now=False,
		)
