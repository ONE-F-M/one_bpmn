"""AMP + HTML-fallback renderer for One BPMN task emails.

Public API
----------
render_amp(task_content: dict) -> str
	AMP4Email document (unbranded, must pass AMP validation).

render_html_fallback(task_content: dict) -> str
	HTML body fragment (no logo, subject header or confidentiality notice).

task_content dict shape
~~~~~~~~~~~~~~~~~~~~~~~
::

	{
		"subject": str,
		"body": str,                # raw HTML from the task
		"actions": [                # optional
			{"label": str, "url": str, "primary": bool},
		],
		"open_link": str,           # "Open in ERPNext" URL
		"comment": bool,            # optional — forces comment variant
		"doctype": str,             # for the form / fallback links
		"name": str,
	}
"""

from __future__ import annotations

import re

import frappe
from markupsafe import Markup

from one_bpmn.email_builder.sanitizer import sanitize_for_amp_with_css

# AMP for Email allows at most 75,000 bytes in the style amp-custom block.
AMP_CUSTOM_CSS_MAX_BYTES = 75_000

_AMP_CUSTOM_RE = re.compile(r"<style amp-custom>(.*?)</style>", re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# AMP Renderer
# ---------------------------------------------------------------------------


def render_amp(task_content: dict) -> str:
	"""Return a complete AMP4Email document.

	Steps:

	1. Sanitise ``task_content["body"]`` for AMP.
	2. Wrap the sanitised body in ``Markup`` so Jinja does not
	   double-escape it (the sanitiser guarantees safety).
	3. Render ``one_bpmn/templates/emails/amp_shell.html``
	   with the sanitised body + actions.

	Args:
		task_content: See module docstring for the expected shape.

	Returns:
		A complete, valid AMP4Email HTML string, or an empty string when the
		style amp-custom block is over 75,000 bytes; the email is then sent
		with the HTML part only.
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


# ---------------------------------------------------------------------------
# HTML Fallback Renderer
# ---------------------------------------------------------------------------


def render_html_fallback(task_content: dict) -> str:
	"""Return the HTML fallback as a body fragment.

	The fragment has no html, head or body tags, no logo, no subject
	header and no confidentiality notice: the email sender wraps it in
	the One-FM default email template, which prints those once.

	Args:
		task_content: See module docstring for the expected shape.

	Returns:
		An HTML fragment with the body, actions, open link and signature.
	"""
	ctx = _build_context(task_content, for_amp=False)
	template = _get_template("one_bpmn/templates/emails/html_fallback.html")
	return template.render(ctx)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _get_template(template_path: str):
	"""Load a Jinja template from the Frappe template search path.

	Args:
		template_path: Dotted-path relative to the Frappe app, e.g.
			``"one_bpmn/templates/emails/amp_shell.html"``.

	Returns:
		A Jinja2 ``Template`` object.

	Raises:
		FileNotFoundError: If the template cannot be found.
	"""
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
	"""Prepare a Jinja context dict from *task_content*.

	Args:
		task_content: See module docstring for the expected shape.
		for_amp: If True the body is sanitised with
			:func:`sanitize_for_amp` and wrapped in ``Markup``.

	Returns:
		A dict ready to pass to ``template.render()``.
	"""
	body = task_content.get("body", "")
	actions = task_content.get("actions") or []
	open_link = task_content.get("open_link", "")

	# Determine variant
	has_actions = bool(actions)

	# A "comment" variant is triggered when:
	#   - task_content explicitly sets comment=True, OR
	#   - there is exactly 1 action whose label starts with "reply"
	is_comment = task_content.get("comment", False) or (
		len(actions) == 1
		and (actions[0].get("label") or "").lower().startswith("reply")
	)

	# Strip Frappe's built-in workflow action buttons from the body
	# to avoid duplication — we render our own AMP/HTML action buttons.
	from one_bpmn.email_builder.sanitizer import _WORKFLOW_BTN_RE
	body = _WORKFLOW_BTN_RE.sub("", body)

	custom_css = ""
	if for_amp:
		clean_body, custom_css = sanitize_for_amp_with_css(body)
		body = Markup(clean_body)

	# Check if any action has a token (for AMP form rendering)
	has_token_actions = any(a.get("token") for a in actions)

	# Build status URL for amp-list (AMP only)
	status_url = ""
	if for_amp and has_token_actions:
		# Find instance_name and task_id from the first token action
		try:
			from one_bpmn.utils.token import generate_status_token, verify_action_token

			first_token = next((a["token"] for a in actions if a.get("token")), None)
			if first_token:
				payload = verify_action_token(first_token)
				status_token = generate_status_token(
					payload["instance_name"], payload["task_id"]
				)
				site_url = frappe.utils.get_url()
				status_url = (
					f"{site_url}/api/method/one_bpmn.api.todo_actions"
					f".get_amp_task_status?status_token={status_token}"
				)
		except Exception:
			pass  # Non-fatal — buttons still work without live status

	# Actions with `extra_fields` (e.g. date inputs) need their own <form> —
	# AMP forms validate all their fields as one atomic unit, so a required
	# field on one action would block submitting a plain token action if
	# they shared a form.
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
