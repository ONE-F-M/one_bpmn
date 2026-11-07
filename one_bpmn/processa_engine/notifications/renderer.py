"""Render the task emails: render_amp gives the AMP4Email document, render_html_fallback the HTML body fragment.

task_content has subject, body (raw HTML), actions ({label, url, primary} dicts), open_link, doctype, name,
and an optional comment flag that forces the comment variant.
"""

from __future__ import annotations

import re

import frappe
from markupsafe import Markup

from one_bpmn.processa_engine.notifications.sanitizer import sanitize_for_amp_with_css

# AMP for Email allows at most 75,000 bytes in the style amp-custom block.
AMP_CUSTOM_CSS_MAX_BYTES = 75_000

LAYOUT_TEMPLATES = {
	name: f"one_bpmn/templates/emails/layouts/{name}.html"
	for name in ("decision_card", "steps", "conversation", "notice")
}
LAYOUT_LANGS = ("en", "ar")
# Rendered outside the status list: AMP email allows no amp-list inside another
LAYOUT_HEADS = {"conversation": "one_bpmn/templates/emails/layouts/conversation_head.html"}
CONFIDENTIALITY_NOTICE = (
	"The content of this email is confidential and intended for the recipient specified in the message "
	"only. It is strictly forbidden to share any part of this message with any third party, without the "
	"written consent of the sender. If you received this message by mistake, please reply to this message "
	"and follow with its deletion, so that we can ensure such a mistake does not occur in the future."
)

_AMP_CUSTOM_RE = re.compile(r"<style amp-custom>(.*?)</style>", re.IGNORECASE | re.DOTALL)



def render_amp(task_content: dict) -> str:
	"""The amp_shell.html AMP4Email document around the sanitised body and actions.

	Empty when the style amp-custom block is over 75,000 bytes; the email then goes with the HTML part only.
	"""
	ctx = _build_context(task_content, for_amp=True)
	template = _get_template("one_bpmn/templates/emails/amp_shell.html")
	html = template.render(ctx)

	match = _AMP_CUSTOM_RE.search(html)
	css_bytes = len(match.group(1).encode("utf-8")) if match else 0
	if css_bytes > AMP_CUSTOM_CSS_MAX_BYTES:
		frappe.log_error(
			title="BPMN: AMP part left out, CSS too large",
			message=(
				f"The style amp-custom block is {css_bytes} bytes, over the "
				f"{AMP_CUSTOM_CSS_MAX_BYTES} byte limit for AMP for Email. "
				f"The email for {task_content.get('doctype', '')} "
				f"{task_content.get('name', '')} is sent with the HTML part only."
			),
		)
		return ""
	return html



def render_html_fallback(task_content: dict) -> str:
	"""The HTML fallback body fragment: body, actions, open link and signature.

	It has no logo, subject header or confidentiality notice; composer.send_email wraps it in bpmn_email.html.
	"""
	ctx = _build_context(task_content, for_amp=False)
	template = _get_template("one_bpmn/templates/emails/html_fallback.html")
	return template.render(ctx)



def render_layout_amp(ctx: dict) -> str:
	"""Return the AMP4EMAIL document: layout_shell.html around the context's layout, in both languages."""
	if ctx.get("status_url"):
		# The layout renders inside the status amp-list template, so text must not open a mustache tag
		ctx = _break_mustache(ctx)
	shell_ctx = _layout_context(ctx, is_amp=True)
	return _get_template("one_bpmn/templates/emails/layout_shell.html").render(shell_ctx)


def render_layout_html(ctx: dict) -> str:
	"""Return the HTML part as a body fragment: the same blocks, English first and the Arabic below."""
	fragment_ctx = _layout_context(ctx, is_amp=False)
	return _get_template("one_bpmn/templates/emails/layout_fallback.html").render(fragment_ctx)


def render_layout_preview(ctx: dict, lang: str) -> str:
	"""Return the HTML part in one language, with the logo row and a foldable Details, for the editor preview."""
	fragment_ctx = {**_layout_context(ctx, is_amp=False), "langs": (lang,), "preview": True}
	return _get_template("one_bpmn/templates/emails/layout_fallback.html").render(fragment_ctx)


def _layout_context(ctx: dict, *, is_amp: bool) -> dict:
	from one_bpmn.processa_engine.notifications.composer import EMAIL_LOGO

	layout = ctx.get("layout")
	if layout not in LAYOUT_TEMPLATES:
		raise ValueError(f"Unknown email layout: {layout!r}")

	status_url = ctx.get("status_url") or ""
	return {
		"facts": [],
		"details": [],
		"attachments": [],
		"open_link": "",
		**ctx,
		"layout_template": LAYOUT_TEMPLATES[layout],
		"head_template": LAYOUT_HEADS.get(layout, ""),
		"langs": LAYOUT_LANGS,
		"is_amp": is_amp,
		"has_status": bool(is_amp and status_url),
		"in_placeholder": False,
		"status_url": status_url,
		"logo": EMAIL_LOGO,
		"CONFIDENTIALITY_NOTICE": CONFIDENTIALITY_NOTICE,
	}


def _break_mustache(value):
	"""Put a zero-width space between doubled braces in every string so amp-mustache prints them as text."""
	if isinstance(value, str):
		return value.replace("{{", "{\u200b{").replace("}}", "}\u200b}")
	if isinstance(value, dict):
		return {k: _break_mustache(v) for k, v in value.items()}
	if isinstance(value, list | tuple):
		return [_break_mustache(v) for v in value]
	return value



def _get_template(template_path: str):
	"""The Jinja template at an app-relative path from Frappe's search path; FileNotFoundError when missing."""
	from frappe.utils.jinja import get_jenv

	env = get_jenv()
	try:
		return env.get_template(template_path)
	except Exception as exc:
		raise FileNotFoundError(
			f"Template not found: {template_path!r}. "
			f"Ensure the file exists under the app's templates directory."
		) from exc


def _build_context(task_content: dict, *, for_amp: bool) -> dict:
	"""The Jinja context for task_content; for_amp sanitises the body and wraps it in Markup."""
	body = task_content.get("body", "")
	actions = task_content.get("actions") or []
	open_link = task_content.get("open_link", "")

	has_actions = bool(actions)

	# Comment variant: comment=True, or a single action whose label starts with "reply"
	is_comment = task_content.get("comment", False) or (
		len(actions) == 1
		and (actions[0].get("label") or "").lower().startswith("reply")
	)

	# Frappe's own workflow buttons are stripped; the email renders its own
	from one_bpmn.processa_engine.notifications.sanitizer import WORKFLOW_BTN_RE
	body = WORKFLOW_BTN_RE.sub("", body)

	custom_css = ""
	if for_amp:
		clean_body, custom_css = sanitize_for_amp_with_css(body)
		body = Markup(clean_body)

	has_token_actions = any(a.get("token") for a in actions)

	status_url = ""
	if for_amp and has_token_actions:
		try:
			from one_bpmn.processa_engine.notifications.token import generate_status_token, verify_action_token

			first_token = next((a["token"] for a in actions if a.get("token")), None)
			if first_token:
				payload = verify_action_token(first_token)
				status_token = generate_status_token(
					payload["instance_name"], payload["task_id"]
				)
				site_url = frappe.utils.get_url()
				status_url = (
					f"{site_url}/api/method/one_bpmn.api.email_actions"
					f".get_amp_task_status?status_token={status_token}"
				)
		except Exception:
			pass  # The buttons work without the live status

	# AMP validates a form as one unit, so actions with extra_fields get their own form
	simple_actions = [a for a in actions if not a.get("extra_fields")]
	complex_actions = [a for a in actions if a.get("extra_fields")]

	return {
		"subject": task_content.get("subject", ""),
		"body": body,
		"custom_css": Markup(custom_css),
		"actions": actions,
		"simple_actions": simple_actions,
		"complex_actions": complex_actions,
		"open_link": open_link,
		"has_actions": has_actions,
		"has_token_actions": has_token_actions,
		"is_comment": is_comment,
		"is_amp": for_amp,
		"doctype": task_content.get("doctype", ""),
		"name": task_content.get("name", ""),
		"site_url": frappe.utils.get_url(),
		"status_url": status_url,
		"action_endpoint": task_content.get("action_endpoint", ""),
		"comment_token": task_content.get("comment_token", ""),
	}
