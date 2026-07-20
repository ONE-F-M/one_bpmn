"""Tests for :mod:`one_bpmn.email_builder.renderer`.

Covers both the AMP and HTML-fallback rendering paths using real Jinja
templates loaded from the filesystem, while mocking Frappe-specific
helpers (``frappe.utils.get_url``, ``get_jinja_env``).

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_renderer
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import jinja2
from frappe.tests.utils import FrappeTestCase

# ---------------------------------------------------------------------------
# Resolve the app root so the Jinja FileSystemLoader can find templates
# via the same relative paths the renderer uses, e.g.
#   "one_bpmn/templates/emails/amp_shell.html"
# ---------------------------------------------------------------------------
APP_ROOT = Path(__file__).resolve().parent.parent.parent


class _RendererTestCase(FrappeTestCase):
	"""Base class that mocks Frappe deps so renderer tests run without a site."""

	def setUp(self):
		env = jinja2.Environment(
			loader=jinja2.FileSystemLoader(str(APP_ROOT)),
			autoescape=False,
		)

		frappe_patch = patch("one_bpmn.email_builder.renderer.frappe")
		self.mock_frappe = frappe_patch.start()
		self.addCleanup(frappe_patch.stop)
		self.mock_frappe.utils.get_url.return_value = "https://erp.test.com"

		template_patch = patch("one_bpmn.email_builder.renderer._get_template")
		mock_get_template = template_patch.start()
		self.addCleanup(template_patch.stop)
		mock_get_template.side_effect = lambda path: env.get_template(path)


# -- Shared task-content dicts ---------------------------------------------

INFO_ONLY: dict = {
	"subject": "Task Update",
	"body": "<p>The document has been updated.</p>",
	"open_link": "https://erp.test.com/app/todo/TODO-001",
	"doctype": "ToDo",
	"name": "TODO-001",
}

WITH_ACTIONS: dict = {
	**INFO_ONLY,
	"subject": "Approval Required",
	"body": "<p>Please review and approve.</p>",
	"actions": [
		{"label": "Approve", "url": "https://erp.test.com/api/approve", "primary": True},
		{"label": "Reject", "url": "https://erp.test.com/api/reject", "primary": False},
	],
}

COMMENT_VARIANT: dict = {
	**INFO_ONLY,
	"subject": "New Comment",
	"body": "<p>A comment was posted.</p>",
	"comment": True,
}


# ---------------------------------------------------------------------------
# AMP renderer tests
# ---------------------------------------------------------------------------

class TestRenderAmp(_RendererTestCase):
	"""Tests for :func:`render_amp`."""

	def test_amp_info_only(self):
		"""Info-only variant includes AMP boilerplate and body; no amp-form."""
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(INFO_ONLY)

		# AMP4Email allows either the "⚡4email" or ASCII "amp4email" form
		# of the required <html> attribute — this template uses the ASCII form.
		self.assertIn("amp4email", html)
		self.assertIn("v0.js", html)
		self.assertIn("The document has been updated.", html)
		self.assertIn("Open in ERPNext", html)
		# The amp-form *extension script* must not be included — note the CSS
		# always contains the literal substring "amp-form" (the
		# .amp-form-submit-success selector), so we check the script tag
		# specifically rather than a raw substring match.
		self.assertNotIn('custom-element="amp-form"', html)
		self.assertNotIn("<form", html)

	def test_amp_with_actions(self):
		"""Action variant renders action buttons as links (no tokens = plain links)."""
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(WITH_ACTIONS)

		# Actions without tokens render as plain <a> links
		self.assertIn("Approve", html)
		self.assertIn("Reject", html)
		self.assertIn("https://erp.test.com/api/approve", html)
		self.assertIn("https://erp.test.com/api/reject", html)

	def test_amp_comment_variant(self):
		"""Comment variant renders amp-mustache, textarea and submit_comment endpoint."""
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(COMMENT_VARIANT)

		self.assertIn("amp-mustache", html)
		self.assertIn("textarea", html)
		self.assertIn("submit_comment", html)

	def test_amp_sanitises_body(self):
		"""Script tags in the body are stripped by the sanitiser."""
		from one_bpmn.email_builder.renderer import render_amp

		payload = {**INFO_ONLY, "body": '<p>Hi</p><script>alert(1)</script>'}
		html = render_amp(payload)

		self.assertNotIn("<script", html.split("</head>", 1)[-1])

	def test_amp_body_not_double_escaped(self):
		"""Sanitised body HTML appears literally, not entity-escaped."""
		from one_bpmn.email_builder.renderer import render_amp

		payload = {**INFO_ONLY, "body": "<p>Hello</p>"}
		html = render_amp(payload)

		self.assertIn("<p>Hello</p>", html)
		self.assertNotIn("&lt;p&gt;", html)


# ---------------------------------------------------------------------------
# HTML fallback renderer tests
# ---------------------------------------------------------------------------

class TestRenderHtmlFallback(_RendererTestCase):
	"""Tests for :func:`render_html_fallback`."""

	def test_html_fallback_has_branding(self):
		"""Fallback email includes the One-FM logo and company name."""
		from one_bpmn.email_builder.renderer import render_html_fallback

		html = render_html_fallback(INFO_ONLY)

		self.assertIn("ONEFM_Identity.png", html)
		self.assertIn("One Facility Management", html)

	def test_html_fallback_has_working_links(self):
		"""Action URLs and the open_link appear as clickable <a> elements."""
		from one_bpmn.email_builder.renderer import render_html_fallback

		html = render_html_fallback(WITH_ACTIONS)

		self.assertIn("https://erp.test.com/api/approve", html)
		self.assertIn("https://erp.test.com/api/reject", html)
		self.assertIn(f'href="{INFO_ONLY["open_link"]}"', html)

	def test_html_fallback_comment_shows_open_link(self):
		"""Comment variant renders an 'Open in ERPNext' link."""
		from one_bpmn.email_builder.renderer import render_html_fallback
		html = render_html_fallback(COMMENT_VARIANT)
		self.assertIn("Open in ERPNext", html)
