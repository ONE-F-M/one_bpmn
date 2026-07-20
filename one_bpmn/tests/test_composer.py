"""Unit tests for :mod:`one_bpmn.email_builder.composer`.

Frappe dependencies are mocked.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_composer
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

_TEST_SECRET = "test-secret-key-for-unit-tests"


def _make_instance(context_doctype="Leave Application", context_docname="HR-LAP-001", name="INST-001", task_cfg=None):
	"""Create a mock BPMN Process Instance."""
	inst = frappe._dict({
		"name": name,
		"doctype": "BPMN Process Instance",
		"context_doctype": context_doctype,
		"context_docname": context_docname,
		"_user_task_extensions": task_cfg or {},
	})
	return inst


class _ComposerTestCase(FrappeTestCase):
	"""Base class that mocks the HMAC secret so token generation is deterministic."""

	def setUp(self):
		secret_patch = patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET)
		secret_patch.start()
		self.addCleanup(secret_patch.stop)


class TestResolveSubjectBody(_ComposerTestCase):

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_inline_config_wins(self, mock_frappe):
		"""Inline notifySubject/notifyBody take priority over template."""
		mock_frappe.render_template = lambda text, ctx: text
		mock_frappe._ = lambda x: x
		from one_bpmn.email_builder.composer import _resolve_subject_body
		task_cfg = {"notifySubject": "My Subject", "notifyBody": "<p>My Body</p>"}
		subject, body = _resolve_subject_body(task_cfg, {}, "Task1", _make_instance())
		self.assertEqual(subject, "My Subject")
		self.assertEqual(body, "<p>My Body</p>")

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_email_template_fallback(self, mock_frappe):
		"""Falls back to Email Template when inline config is empty."""
		tmpl = MagicMock()
		tmpl.subject = "Template Subject"
		tmpl.response = "<p>Template Body</p>"
		mock_frappe.get_doc.return_value = tmpl
		mock_frappe.render_template = lambda text, ctx: text
		mock_frappe._ = lambda x: x
		from one_bpmn.email_builder.composer import _resolve_subject_body
		task_cfg = {"notifyTemplate": "My Template"}
		subject, body = _resolve_subject_body(task_cfg, {}, "Task1", _make_instance())
		self.assertEqual(subject, "Template Subject")
		self.assertEqual(body, "<p>Template Body</p>")

	@patch("one_bpmn.email_builder.composer._", side_effect=lambda x: x)
	@patch("one_bpmn.email_builder.composer.frappe")
	def test_default_fallback(self, mock_frappe, mock_translate):
		"""Falls back to defaults when no config provided."""
		mock_frappe.render_template = lambda text, ctx: text
		from one_bpmn.email_builder.composer import _resolve_subject_body
		task_cfg = {}
		subject, body = _resolve_subject_body(task_cfg, {}, "Task1", _make_instance())
		self.assertTrue("Task1" in subject or "INST-001" in subject)
		self.assertIn("<p>", body)


class TestBuildOpenLink(_ComposerTestCase):

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_with_context_doc(self, mock_frappe):
		"""Builds /app/{slug}/{docname} when context doc exists."""
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		from one_bpmn.email_builder.composer import _build_open_link
		link = _build_open_link(_make_instance())
		self.assertEqual(link, "https://erp.test.com/app/leave-application/HR-LAP-001")

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_without_context_doc(self, mock_frappe):
		"""Falls back to BPMN instance link when no context."""
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		from one_bpmn.email_builder.composer import _build_open_link
		link = _build_open_link(_make_instance(context_doctype="", context_docname=""))
		self.assertEqual(link, "https://erp.test.com/app/bpmn-process-instance/INST-001")


class TestBuildActionsForEmail(_ComposerTestCase):

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_simple_actions_get_tokens(self, mock_frappe):
		"""Simple actions get HMAC tokens (have 'token' key)."""
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		from one_bpmn.email_builder.composer import _build_actions_for_email
		task_cfg = {"taskActions": json.dumps([{"action": "Approve"}, {"action": "Reject"}])}
		actions = _build_actions_for_email(task_cfg, _make_instance(), "task-uuid", "user@test.com", "https://erp.test.com/app/leave")
		self.assertEqual(len(actions), 2)
		self.assertIn("token", actions[0])  # HMAC token present
		self.assertEqual(actions[0]["label"], "Approve")
		self.assertEqual(actions[1]["label"], "Reject")

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_confirm_actions_get_links(self, mock_frappe):
		"""Actions with confirmTransition=true get plain URLs, no tokens."""
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		from one_bpmn.email_builder.composer import _build_actions_for_email
		task_cfg = {"taskActions": json.dumps([{"action": "Approve", "confirmTransition": "true"}])}
		actions = _build_actions_for_email(task_cfg, _make_instance(), "task-uuid", "user@test.com", "https://erp.test.com/app/leave")
		self.assertEqual(len(actions), 1)
		self.assertNotIn("token", actions[0])
		self.assertIn("url", actions[0])
		self.assertEqual(actions[0]["url"], "https://erp.test.com/app/leave")

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_empty_actions(self, mock_frappe):
		"""No taskActions returns empty list."""
		from one_bpmn.email_builder.composer import _build_actions_for_email
		actions = _build_actions_for_email({}, _make_instance(), "task-uuid", "user@test.com", "")
		self.assertEqual(actions, [])


class TestSendEmail(_ComposerTestCase):

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_sets_amp_flag(self, mock_frappe):
		"""Sets frappe.flags.amp_html before sending."""
		# Make one_fm import fail so it falls back to frappe.sendmail
		with patch.dict("sys.modules", {"one_fm": None, "one_fm.processor": None}):
			mock_frappe.sendmail = MagicMock()
			from one_bpmn.email_builder.composer import _send_email
			_send_email(["user@test.com"], "Subject", "<p>Body</p>", "<html amp>AMP</html>")
			self.assertEqual(mock_frappe.flags.amp_html, "<html amp>AMP</html>")

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_fallback_to_frappe_sendmail(self, mock_frappe):
		"""Falls back to frappe.sendmail when one_fm is not available."""
		with patch.dict("sys.modules", {"one_fm": None, "one_fm.processor": None}):
			mock_frappe.sendmail = MagicMock()
			mock_frappe.db.get_value = MagicMock(return_value=None)
			from one_bpmn.email_builder.composer import _send_email
			_send_email(["user@test.com"], "Test", "<p>Body</p>", "")
			mock_frappe.sendmail.assert_called_once()


class TestComposeAndSendTaskEmail(_ComposerTestCase):

	@patch("one_bpmn.email_builder.composer._send_email")
	@patch("one_bpmn.email_builder.composer._build_open_link", return_value="https://erp.test.com/app/leave/HR-LAP-001")
	@patch("one_bpmn.email_builder.composer._get_context_doc", return_value=MagicMock())
	@patch("one_bpmn.email_builder.composer.frappe")
	def test_skips_when_notify_false(self, mock_frappe, mock_ctx, mock_link, mock_send):
		"""Does nothing when notifyAssignee is not 'true'."""
		from one_bpmn.email_builder.composer import compose_and_send_task_email
		inst = _make_instance(task_cfg={"Activity_1": {"notifyAssignee": "false"}})
		compose_and_send_task_email(inst, "user@test.com", "Task", "t-1", "Activity_1")
		mock_send.assert_not_called()

	@patch("one_bpmn.email_builder.composer._send_email")
	@patch("one_bpmn.email_builder.composer._build_open_link", return_value="https://erp.test.com/app/leave/HR-LAP-001")
	@patch("one_bpmn.email_builder.composer._get_context_doc", return_value=MagicMock())
	@patch("one_bpmn.email_builder.composer.frappe")
	def test_sends_when_notify_true(self, mock_frappe, mock_ctx, mock_link, mock_send):
		"""Sends email when notifyAssignee is 'true'."""
		mock_frappe.render_template = lambda text, ctx: text
		mock_frappe._ = lambda x: x
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"

		with patch("one_bpmn.email_builder.renderer.frappe", mock_frappe):
			with patch("one_bpmn.email_builder.renderer._get_template") as mock_tmpl:
				import jinja2
				from pathlib import Path
				app_root = Path(__file__).resolve().parent.parent.parent
				env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(app_root)), autoescape=False)
				mock_tmpl.side_effect = lambda p: env.get_template(p)

				from one_bpmn.email_builder.composer import compose_and_send_task_email
				inst = _make_instance(task_cfg={"Activity_1": {
					"notifyAssignee": "true",
					"notifySubject": "Approve Leave",
					"notifyBody": "<p>Please approve</p>",
					"taskActions": json.dumps([{"action": "Approve"}]),
				}})
				compose_and_send_task_email(inst, "user@test.com", "Task", "t-1", "Activity_1")
				mock_send.assert_called_once()
				args = mock_send.call_args
				self.assertTrue(
					args.kwargs.get("recipients") == ["user@test.com"]
					or args[1].get("recipients") == ["user@test.com"]
					or args[0][0] == ["user@test.com"]
				)
