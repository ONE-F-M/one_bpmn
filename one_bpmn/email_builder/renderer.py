"""AMP + HTML-fallback renderer for One BPMN task emails.

Public API
----------
render_amp(task_content: dict) -> str
	AMP4Email document (unbranded, must pass AMP validation).

render_html_fallback(task_content: dict) -> str
	Branded HTML email via the Frappe Jinja environment.

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

import frappe
from markupsafe import Markup

from one_bpmn.email_builder.sanitizer import sanitize_for_amp


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
		A complete, valid AMP4Email HTML string.
	"""
	ctx = _build_context(task_content, for_amp=True)
	template = _get_template("one_bpmn/templates/emails/amp_shell.html")
	return template.render(ctx)


# ---------------------------------------------------------------------------
# HTML Fallback Renderer
# ---------------------------------------------------------------------------


def render_html_fallback(task_content: dict) -> str:
	"""Return a branded HTML fallback email.

	Uses the standard Frappe Jinja environment so it picks up the
	One-FM branded template with logo, signature, social icons, and
	confidentiality footer.

	Args:
		task_content: See module docstring for the expected shape.

	Returns:
		A complete HTML email string with One-FM branding.
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

	if for_amp:
		body = Markup(sanitize_for_amp(body))

	# Check if any action has a token (for AMP form rendering)
	has_token_actions = any(a.get("token") for a in actions)

	return {
		"subject": task_content.get("subject", ""),
		"body": body,
		"actions": actions,
		"open_link": open_link,
		"has_actions": has_actions,
		"has_token_actions": has_token_actions,
		"is_comment": is_comment,
		"is_amp": for_amp,
		"doctype": task_content.get("doctype", ""),
		"name": task_content.get("name", ""),
		"site_url": frappe.utils.get_url(),
	}
