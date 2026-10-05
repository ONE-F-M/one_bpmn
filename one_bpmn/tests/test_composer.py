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
	def test_modeler_fields_win_and_body_is_decoded(self, mock_frappe):
		"""notifyAssigneeSubject / notifyAssigneeBody (base64) beat the legacy keys."""
		import base64
		mock_frappe.render_template = lambda text, ctx: text
		mock_frappe._ = lambda x: x
		from one_bpmn.email_builder.composer import _resolve_subject_body
		task_cfg = {
			"notifyAssigneeSubject": "Modeler Subject",
			"notifyAssigneeBody": base64.b64encode(b"<p>Modeler Body</p>").decode(),
			"notifySubject": "Legacy Subject",
			"notifyBody": "<p>Legacy Body</p>",
		}
		subject, body = _resolve_subject_body(task_cfg, {}, "Task1", _make_instance())
		self.assertEqual(subject, "Modeler Subject")
		self.assertEqual(body, "<p>Modeler Body</p>")

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
	def test_hd_ticket_goes_to_helpdesk(self, mock_frappe):
		"""HD Ticket links to the Helpdesk portal, not the desk form."""
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		from one_bpmn.email_builder.composer import _build_open_link
		link = _build_open_link(_make_instance("HD Ticket", "TICKET-0042"))
		self.assertEqual(link, "https://erp.test.com/helpdesk/tickets/TICKET-0042")

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_hd_ticket_child_doctype_still_desk(self, mock_frappe):
		"""Only HD Ticket itself has a portal page; its children do not."""
		mock_frappe.utils.get_url.return_value = "https://erp.test.com"
		from one_bpmn.email_builder.composer import _build_open_link
		link = _build_open_link(_make_instance("HD Ticket Comment", "COMM-001"))
		self.assertEqual(link, "https://erp.test.com/app/hd-ticket-comment/COMM-001")

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
	def test_sets_amp_flag_for_the_send_and_clears_it_after(self, mock_frappe):
		"""The flag is set while sendmail runs and gone once _send_email returns."""
		seen = []
		with patch.dict("sys.modules", {"one_fm": None, "one_fm.processor": None}):
			mock_frappe.sendmail = MagicMock(side_effect=lambda **kw: seen.append(mock_frappe.flags.amp_html))
			from one_bpmn.email_builder.composer import _send_email
			_send_email(["user@test.com"], "Subject", "<p>Body</p>", "<html amp>AMP</html>")
		self.assertEqual(seen, ["<html amp>AMP</html>"])
		self.assertIsNone(mock_frappe.flags.amp_html)

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_clears_amp_flag_even_when_the_send_raises(self, mock_frappe):
		with patch.dict("sys.modules", {"one_fm": None, "one_fm.processor": None}):
			mock_frappe.sendmail = MagicMock(side_effect=RuntimeError("smtp down"))
			from one_bpmn.email_builder.composer import _send_email
			with self.assertRaises(RuntimeError):
				_send_email(["user@test.com"], "Subject", "<p>Body</p>", "<html amp>AMP</html>")
		self.assertIsNone(mock_frappe.flags.amp_html)

	@patch("one_bpmn.email_builder.composer.frappe")
	def test_one_fm_send_is_external_mail_with_cc(self, mock_frappe):
		"""Notify Assignee is an explicit opt-in, so the recipient preference filter is bypassed."""
		import sys
		import types
		fake_proc = types.ModuleType("one_fm.processor")
		fake_proc.sendemail = MagicMock()
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")
		with patch.dict(sys.modules, {"one_fm": fake_root, "one_fm.processor": fake_proc}):
			from one_bpmn.email_builder.composer import _send_email
			_send_email(["user@test.com"], "Subject", "<p>Body</p>", "", cc="cc@test.com")
		kwargs = fake_proc.sendemail.call_args.kwargs
		self.assertTrue(kwargs["is_external_mail"])
		self.assertEqual(kwargs["cc"], "cc@test.com")

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
					"notifyAssigneeAccount": "Notifications",
					"taskActions": json.dumps([{"action": "Approve"}]),
				}})
				compose_and_send_task_email(inst, "user@test.com", "Task", "t-1", "Activity_1")
				mock_send.assert_called_once()
				args = mock_send.call_args
				self.assertEqual(args.kwargs.get("sender_account"), "Notifications")
				self.assertTrue(
					args.kwargs.get("recipients") == ["user@test.com"]
					or args[1].get("recipients") == ["user@test.com"]
					or args[0][0] == ["user@test.com"]
				)
