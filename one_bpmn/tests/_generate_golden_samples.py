"""Generate golden AMP sample HTML files for CI validation.

Run with: python -m one_bpmn.tests._generate_golden_samples
"""

from __future__ import annotations

import sys
from pathlib import Path

import jinja2
from markupsafe import Markup

# Add app root to path so imports work
APP_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(APP_ROOT))

from one_bpmn.email_builder.sanitizer import sanitize_for_amp

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _render_amp(template_path: str, task_content: dict) -> str:
	"""Render an AMP template without Frappe."""
	env = jinja2.Environment(
		loader=jinja2.FileSystemLoader(str(APP_ROOT)),
		autoescape=False,
	)
	template = env.get_template(template_path)

	body = task_content.get("body", "")
	actions = task_content.get("actions") or []
	open_link = task_content.get("open_link", "")
	has_actions = bool(actions)
	is_comment = task_content.get("comment", False) or (
		len(actions) == 1
		and (actions[0].get("label") or "").lower().startswith("reply")
	)

	comment_token = ""
	if is_comment:
		# Deterministic dummy secret so this script needs no Frappe site.
		from unittest.mock import patch

		with patch("one_bpmn.utils.token._get_secret", return_value="golden-sample-secret"):
			from one_bpmn.utils.token import generate_doc_action_token

			comment_token = generate_doc_action_token(
				task_content.get("doctype", ""),
				task_content.get("name", ""),
				"Comment",
				"golden-sample-user@one-fm.com",
			)

	# Mirrors one_bpmn.email_builder.renderer._build_context — kept in sync
	# manually since this script must run without a Frappe site.
	simple_actions = [a for a in actions if not a.get("extra_fields")]
	complex_actions = [a for a in actions if a.get("extra_fields")]

	ctx = {
		"subject": task_content.get("subject", ""),
		"body": Markup(sanitize_for_amp(body)),
		"actions": actions,
		"simple_actions": simple_actions,
		"complex_actions": complex_actions,
		"action_endpoint": task_content.get("action_endpoint", ""),
		"open_link": open_link,
		"has_actions": has_actions,
		"has_token_actions": any(a.get("token") for a in actions),
		"is_comment": is_comment,
		"comment_token": comment_token,
		"is_amp": True,
		"doctype": task_content.get("doctype", ""),
		"name": task_content.get("name", ""),
		"site_url": "https://erp.one-fm.com",
	}
	return template.render(ctx)


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

TEMPLATE_PATH = "one_bpmn/templates/emails/amp_shell.html"


def main():
	FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

	samples = {
		"golden_amp_info.html": INFO_CONTENT,
		"golden_amp_action.html": ACTION_CONTENT,
		"golden_amp_comment.html": COMMENT_CONTENT,
	}

	for filename, content in samples.items():
		html = _render_amp(TEMPLATE_PATH, content)
		out = FIXTURES_DIR / filename
		out.write_text(html, encoding="utf-8")
		print(f"  ✓ {out}")

	print(f"\nGenerated {len(samples)} golden samples in {FIXTURES_DIR}")


if __name__ == "__main__":
	main()
