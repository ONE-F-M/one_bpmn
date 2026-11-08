# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Email Notification service tasks sent as the Notice layout, and the custom HTML path left as it was."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.email_builder.composer import compose_and_send_info_email, sends_notice
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_email
from one_bpmn.tests.test_amp_validation import _validate_amp4email


def _notice_cfg(**extra):
	return {
		"emailTo": "a@one-fm.com, b@one-fm.com",
		"emailToDocFields": "allocated_to",
		"emailUseDoctype": "true",
		"emailDoctype": "ToDo",
		"emailLayout": "notice",
		"emailSubject": "ToDo {{ doc.name }} closed",
		"emailSubjectAr": "تم إغلاق {{ doc.name }}",
		"emailHeadingEn": "Closed",
		"emailHeadingAr": "مغلق",
		"emailMessageEn": "The ToDo {{ doc.description }} is closed.",
		"emailMessageAr": "تم إغلاق المهمة.",
		"emailShowStatus": "true",
		"emailFacts": json.dumps(["description", ["status", "description"]]),
		**extra,
	}


class TestNoticeLayout(FrappeTestCase):
	def setUp(self):
		clear_cache()
		self.todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "Fix the gate", "allocated_to": "Administrator"}
		).insert()
		self.instance = frappe._dict(
			name="INST-NOTICE",
			doctype="BPMN Process Instance",
			context_doctype="ToDo",
			context_docname=self.todo.name,
		)

	def _send(self, cfg):
		"""Run the service task; returns the sendmail kwargs and the AMP part it carried."""
		sent = []

		def capture(**kwargs):
			sent.append((kwargs, frappe.flags.amp_html))

		with patch("one_bpmn.email_builder.composer.frappe.sendmail", side_effect=capture):
			dispatch_email(self.instance, None, cfg)
		self.assertEqual(len(sent), 1)
		return sent[0]

	def test_the_layout_decides_the_path(self):
		self.assertTrue(sends_notice({"emailLayout": "notice", "emailBody": "<p>x</p>"}))
		self.assertTrue(sends_notice({}))
		self.assertFalse(sends_notice({"emailBody": "<p>x</p>"}))
		self.assertFalse(sends_notice({"emailLayout": "html"}))

	def test_one_send_with_both_languages_in_the_subject(self):
		kwargs, amp = self._send(_notice_cfg())

		admin_email = frappe.db.get_value("User", "Administrator", "email")
		self.assertEqual(kwargs["recipients"], ["a@one-fm.com", "b@one-fm.com", admin_email])
		self.assertEqual(kwargs["subject"], f"ToDo {self.todo.name} closed || تم إغلاق {self.todo.name}")
		self.assertIn("<html amp4email", amp)

	def test_no_arabic_subject_sends_the_english_only(self):
		kwargs, _amp = self._send(_notice_cfg(emailSubjectAr=""))
		self.assertEqual(kwargs["subject"], f"ToDo {self.todo.name} closed")

	def test_the_blocks_come_in_order_with_no_buttons(self):
		_kwargs, amp = self._send(_notice_cfg())
		english = amp.split('lang="ar"')[0]

		order = [
			english.index("{{workflow_state}}"),
			english.index("ToDo · Notice"),
			english.index(">Closed</h3>"),
			english.index("The ToDo Fix the gate is closed."),
			english.index('class="facts"'),
		]
		self.assertEqual(order, sorted(order))
		self.assertIn(
			'<div placeholder class="ph"><div class="pane" lang="en" dir="ltr"><div class="live">', amp
		)
		self.assertIn("مغلق", amp)
		self.assertIn("إشعار", amp)
		for absent in ("<form", '<button type="submit"', "handle_amp_action"):
			self.assertNotIn(absent, amp)

	def test_live_status_is_a_status_token_without_a_task(self):
		from one_bpmn.utils.token import verify_action_token

		_kwargs, amp = self._send(_notice_cfg())
		token = amp.split("status_token=")[1].split('"')[0]
		payload = verify_action_token(token)

		self.assertEqual(payload["type"], "status")
		self.assertEqual(payload["task_id"], "")
		self.assertNotIn("user", payload)

	def test_status_off_has_no_status_block(self):
		_kwargs, amp = self._send(_notice_cfg(emailShowStatus=""))
		self.assertNotIn("<amp-list", amp)
		self.assertNotIn('class="live', amp)

	def test_no_heading_uses_the_subject_and_no_message_has_no_block(self):
		_kwargs, amp = self._send(
			_notice_cfg(emailHeadingEn="", emailHeadingAr="", emailMessageEn="", emailMessageAr="")
		)
		self.assertIn(f">ToDo {self.todo.name} closed</h3>", amp)
		self.assertNotIn('class="msg"', amp)

	def test_attachments_are_listed_with_links_that_last_30_days(self):
		links = [{"file_name": "plan.pdf", "url": "https://erp.example.com/file?token=t"}]
		with patch("one_bpmn.email_builder.fields.build_attachment_links", return_value=links) as build:
			kwargs, amp = self._send(_notice_cfg(emailAttachments="true"))

		self.assertEqual(build.call_args.args[1], 720)
		self.assertIn("plan.pdf", amp)
		self.assertIn("plan.pdf", kwargs["args"]["message"])

	def test_the_amp_part_passes_the_validator_with_and_without_status(self):
		_validate_amp4email(self._send(_notice_cfg())[1], "notice_status")
		_validate_amp4email(self._send(_notice_cfg(emailShowStatus=""))[1], "notice_plain")

	def test_a_failed_amp_part_sends_the_html_part_only(self):
		with (
			patch("one_bpmn.email_builder.renderer.render_layout_amp", side_effect=ValueError("bad")),
			patch("one_bpmn.email_builder.composer.frappe.log_error") as log_error,
		):
			kwargs, amp = self._send(_notice_cfg())

		self.assertFalse(amp)
		self.assertIn("Fix the gate", kwargs["args"]["message"])
		self.assertEqual(log_error.call_args.kwargs["title"], "BPMN: Notice AMP render failed")

	def test_a_failed_html_part_is_logged_and_raised(self):
		with (
			patch("one_bpmn.email_builder.renderer.render_layout_html", side_effect=ValueError("bad")),
			patch("one_bpmn.email_builder.composer.frappe.log_error") as log_error,
			patch("one_bpmn.email_builder.composer.frappe.sendmail") as sendmail,
		):
			with self.assertRaises(ValueError):
				dispatch_email(self.instance, None, _notice_cfg())

		sendmail.assert_not_called()
		self.assertEqual(log_error.call_args.kwargs["title"], "BPMN: Notice email render failed")

	def test_a_custom_html_body_is_sent_as_before(self):
		cfg = {
			"emailTo": "a@one-fm.com",
			"emailSubject": "Hello {{ doc.name }}",
			"emailBody": "<p>{{ doc.description }}</p>",
		}
		kwargs, amp = self._send(cfg)

		subject = f"Hello {self.todo.name}"
		self.assertEqual(kwargs["subject"], subject)
		self.assertEqual(kwargs["args"]["message"], "<p>Fix the gate</p>")
		self.assertEqual(amp, compose_and_send_info_email(self.instance, cfg, subject, "<p>Fix the gate</p>"))
