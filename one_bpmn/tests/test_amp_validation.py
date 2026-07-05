"""AMP validation tests using golden samples.

These tests render AMP documents from fixture data and validate them
against the official AMP validator.  They also validate the committed
golden-sample HTML files for regression coverage.

Requirements:
	- Node.js with ``amphtml-validator`` available via ``npx``
	  (install globally: ``npm install -g amphtml-validator``)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Validator binary — try global first, fall back to npx
_VALIDATOR_CMD: list[str] | None = None


def _get_validator_cmd() -> list[str]:
	"""Locate the amphtml-validator binary."""
	global _VALIDATOR_CMD
	if _VALIDATOR_CMD is not None:
		return _VALIDATOR_CMD

	if shutil.which("amphtml-validator"):
		_VALIDATOR_CMD = ["amphtml-validator"]
	elif shutil.which("npx"):
		_VALIDATOR_CMD = ["npx", "--yes", "amphtml-validator"]
	else:
		pytest.skip("amphtml-validator not found; install via: npm install -g amphtml-validator")

	return _VALIDATOR_CMD


def _validate_amp4email(html: str, label: str = "amp_doc") -> None:
	"""Write *html* to a temp file and run the AMP validator against it.

	Asserts that the validator exits with code 0 (PASS).
	"""
	cmd = _get_validator_cmd()
	with tempfile.NamedTemporaryFile(
		mode="w", suffix=".html", prefix=f"amp_{label}_", delete=False
	) as f:
		f.write(html)
		f.flush()
		tmp_path = f.name

	result = subprocess.run(
		[*cmd, "--html_format", "AMP4EMAIL", tmp_path],
		capture_output=True,
		text=True,
		timeout=30,
	)
	Path(tmp_path).unlink(missing_ok=True)

	assert result.returncode == 0, (
		f"AMP validation FAILED for {label}:\n"
		f"STDOUT: {result.stdout}\n"
		f"STDERR: {result.stderr}"
	)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

INFO_CONTENT = {
	"subject": "Document Updated",
	"body": "<p>The purchase order <strong>PO-2024-001</strong> has been updated.</p>",
	"open_link": "https://erp.one-fm.com/app/purchase-order/PO-2024-001",
	"doctype": "Purchase Order",
	"name": "PO-2024-001",
}

ACTION_CONTENT = {
	"subject": "Approval Required",
	"body": "<p>Please review and take action on this leave application.</p>",
	"actions": [
		{"label": "Approve", "url": "https://erp.one-fm.com/api/approve", "primary": True},
		{"label": "Reject", "url": "https://erp.one-fm.com/api/reject", "primary": False},
	],
	"open_link": "https://erp.one-fm.com/app/leave-application/LA-2024-001",
	"doctype": "Leave Application",
	"name": "LA-2024-001",
}

COMMENT_CONTENT = {
	"subject": "New Comment on Task",
	"body": "<p>Kartik posted a comment on your task.</p>",
	"comment": True,
	"open_link": "https://erp.one-fm.com/app/todo/TODO-001",
	"doctype": "ToDo",
	"name": "TODO-001",
}


# ---------------------------------------------------------------------------
# Golden sample tests (committed files)
# ---------------------------------------------------------------------------


class TestGoldenSamples:
	"""Validate the committed golden AMP sample files."""

	@pytest.mark.parametrize(
		"filename",
		[
			"golden_amp_info.html",
			"golden_amp_action.html",
			"golden_amp_comment.html",
		],
	)
	def test_golden_file_passes_validation(self, filename: str) -> None:
		"""Each committed golden sample must pass AMP4EMAIL validation."""
		path = FIXTURES_DIR / filename
		if not path.exists():
			pytest.skip(f"Golden sample not yet generated: {filename}")
		html = path.read_text(encoding="utf-8")
		_validate_amp4email(html, label=filename)


# ---------------------------------------------------------------------------
# Dynamic render + validate tests
# ---------------------------------------------------------------------------


class TestRenderedAmpValidation:
	"""Render AMP docs from fixture data and validate them."""

	@pytest.fixture(autouse=True)
	def _setup_frappe_mocks(self):
		"""Mock Frappe so render_amp() works without a site."""
		import jinja2
		from unittest.mock import patch

		app_root = Path(__file__).resolve().parent.parent.parent
		env = jinja2.Environment(
			loader=jinja2.FileSystemLoader(str(app_root)),
			autoescape=False,
		)

		with patch("one_bpmn.email_builder.renderer.frappe") as mock_frappe:
			mock_frappe.utils.get_url.return_value = "https://erp.one-fm.com"
			with patch("one_bpmn.email_builder.renderer._get_template") as mock_tmpl:
				mock_tmpl.side_effect = lambda p: env.get_template(p)
				yield

	def test_info_only_renders_valid_amp(self) -> None:
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(INFO_CONTENT)
		_validate_amp4email(html, label="info_only")

	def test_action_renders_valid_amp(self) -> None:
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(ACTION_CONTENT)
		_validate_amp4email(html, label="action")

	def test_comment_renders_valid_amp(self) -> None:
		from one_bpmn.email_builder.renderer import render_amp

		html = render_amp(COMMENT_CONTENT)
		_validate_amp4email(html, label="comment")

	def test_sanitised_body_still_validates(self) -> None:
		"""A body with dangerous HTML still produces valid AMP after sanitisation."""
		from one_bpmn.email_builder.renderer import render_amp

		dirty_content = {
			**INFO_CONTENT,
			"body": (
				'<p>Hello</p><script>alert("xss")</script>'
				'<style>body{display:none}</style>'
				'<img src="https://example.com/photo.jpg">'
				'<iframe src="evil.html"></iframe>'
			),
		}
		html = render_amp(dirty_content)
		_validate_amp4email(html, label="sanitised_body")
