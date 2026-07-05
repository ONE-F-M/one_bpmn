"""Tests for :mod:`one_bpmn.email_builder.renderer`.

Covers both the AMP and HTML-fallback rendering paths using real Jinja
templates loaded from the filesystem, while mocking Frappe-specific
helpers (``frappe.utils.get_url``, ``get_jinja_env``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import jinja2
import pytest

# ---------------------------------------------------------------------------
# Resolve the app root so the Jinja FileSystemLoader can find templates
# via the same relative paths the renderer uses, e.g.
#   "one_bpmn/templates/emails/amp_shell.html"
# ---------------------------------------------------------------------------
APP_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_frappe():
	"""Patch Frappe dependencies so renderer tests run without a site."""
	env = jinja2.Environment(
		loader=jinja2.FileSystemLoader(str(APP_ROOT)),
		autoescape=False,
	)

	with patch("one_bpmn.email_builder.renderer.frappe") as mock_frappe:
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		with patch("one_bpmn.email_builder.renderer._get_template") as mock_get_template:

			def _side_effect(path: str):
				return env.get_template(path)

			mock_get_template.side_effect = _side_effect
			yield mock_frappe


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

class TestRenderAmp:
	"""Tests for :func:`render_amp`."""

	def test_amp_info_only(self):
		"""Info-only variant includes AMP boilerplate and body; no amp-form."""
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(INFO_ONLY)

		assert "⚡4email" in html
		assert "v0.js" in html
		assert "The document has been updated." in html
		assert "Open in ERPNext" in html
		assert "amp-form" not in html

	def test_amp_with_actions(self):
		"""Action variant renders action buttons as links (no tokens = plain links)."""
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(WITH_ACTIONS)

		# Actions without tokens render as plain <a> links
		assert "Approve" in html
		assert "Reject" in html
		assert "https://erp.test.com/api/approve" in html
		assert "https://erp.test.com/api/reject" in html

	def test_amp_comment_variant(self):
		"""Comment variant renders amp-mustache, textarea and submit_comment endpoint."""
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(COMMENT_VARIANT)

		assert "amp-mustache" in html
		assert "textarea" in html
		assert "submit_comment" in html

	def test_amp_sanitises_body(self):
		"""Script tags in the body are stripped by the sanitiser."""
		from one_bpmn.email_builder.renderer import render_amp

		payload = {**INFO_ONLY, "body": '<p>Hi</p><script>alert(1)</script>'}
		html = render_amp(payload)

		assert "<script" not in html.split("</head>", 1)[-1]

	def test_amp_body_not_double_escaped(self):
		"""Sanitised body HTML appears literally, not entity-escaped."""
		from one_bpmn.email_builder.renderer import render_amp

		payload = {**INFO_ONLY, "body": "<p>Hello</p>"}
		html = render_amp(payload)

		assert "<p>Hello</p>" in html
		assert "&lt;p&gt;" not in html


# ---------------------------------------------------------------------------
# HTML fallback renderer tests
# ---------------------------------------------------------------------------

class TestRenderHtmlFallback:
	"""Tests for :func:`render_html_fallback`."""

	def test_html_fallback_has_branding(self):
		"""Fallback email includes the One-FM logo and company name."""
		from one_bpmn.email_builder.renderer import render_html_fallback

		html = render_html_fallback(INFO_ONLY)

		assert "ONEFM_Identity.png" in html
		assert "One Facility Management" in html

	def test_html_fallback_has_working_links(self):
		"""Action URLs and the open_link appear as clickable <a> elements."""
		from one_bpmn.email_builder.renderer import render_html_fallback

		html = render_html_fallback(WITH_ACTIONS)

		assert "https://erp.test.com/api/approve" in html
		assert "https://erp.test.com/api/reject" in html
		assert f'href="{INFO_ONLY["open_link"]}"' in html

	def test_html_fallback_comment_shows_open_link(self):
		"""Comment variant renders an 'Open in ERPNext' link."""
		from one_bpmn.email_builder.renderer import render_html_fallback
		html = render_html_fallback(COMMENT_VARIANT)
		assert "Open in ERPNext" in html
