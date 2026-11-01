# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""preview_notification: the draft Email Notification rendered for the latest record, with nothing sent."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.api import notification_api
from one_bpmn.api.notification_api import preview_notification

NOTICE = {
	"emailLayout": "notice",
	"emailSubject": "ToDo {{ doc.name }} closed",
	"emailSubjectAr": "تم الإغلاق",
	"emailHeadingEn": "Closed",
	"emailMessageEn": "{{ doc.description }} is closed.",
	"emailShowStatus": "true",
	"emailAttachments": "true",
	"emailFacts": json.dumps(["description"]),
}


class TestEmailPreview(FrappeTestCase):
	def setUp(self):
		clear_cache()
		self.todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "Fix the gate", "allocated_to": "Administrator"}
		).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _preview(self, cfg, doctype="ToDo", element_type="send_email"):
		real_get_list = frappe.get_list

		def get_list(doctype, *args, **kwargs):
			if doctype == "File":
				return ["plan.pdf"]
			return real_get_list(doctype, *args, **kwargs)

		with patch.object(notification_api.frappe, "get_list", side_effect=get_list):
			return preview_notification("", element_type, doctype, json.dumps(cfg))

	def test_the_notice_is_rendered_for_the_latest_record(self):
		result = self._preview(NOTICE)

		self.assertEqual(result["docname"], self.todo.name)
		self.assertEqual(result["subject"], f"ToDo {self.todo.name} closed || تم الإغلاق")
		html = result["html"]
		for text in (
			"ToDo · Notice",
			">Closed</h3>",
			"Fix the gate is closed.",
			'class="facts"',
			"تم الإغلاق",
		):
			self.assertIn(text, html)
		self.assertIn('<div class="row">plan.pdf</div>', html)

	def test_custom_html_is_rendered_as_today(self):
		result = self._preview(
			{"emailLayout": "html", "emailSubject": "Hi", "emailBody": "<p>{{ doc.description }}</p>"}
		)
		self.assertIn("<p>Fix the gate</p>", result["html"])
		self.assertNotIn("Notice", result["html"])

	def test_nothing_is_sent_and_no_token_is_made(self):
		queued = frappe.db.count("Email Queue")
		with (
			patch("one_bpmn.utils.token.generate_status_token") as status_token,
			patch("one_bpmn.email_builder.fields.generate_file_token") as file_token,
			patch("one_bpmn.utils.token.generate_action_token") as action_token,
			patch.object(frappe, "sendmail") as sendmail,
		):
			result = self._preview(NOTICE)

		self.assertNotIn("token=", result["html"])
		for mock in (status_token, file_token, action_token, sendmail):
			mock.assert_not_called()
		self.assertEqual(frappe.db.count("Email Queue"), queued)

	def test_no_record_says_so(self):
		with patch.object(notification_api.frappe, "get_list", return_value=[]):
			result = preview_notification("", "send_email", "ToDo", json.dumps(NOTICE))
		self.assertEqual(result, {"message": "No ToDo record to preview yet"})

	def test_broken_jinja_returns_the_error_and_logs_it(self):
		with patch.object(notification_api.frappe, "log_error") as log_error:
			result = self._preview({**NOTICE, "emailHeadingEn": "{{ doc.name | no_such_filter }}"})

		self.assertIn("no_such_filter", result["error"])
		self.assertNotIn("<pre>", result["error"])
		self.assertEqual(frappe.local.message_log, [])
		log_error.assert_called_once()

	def test_a_user_who_cannot_edit_process_models_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			preview_notification("", "send_email", "ToDo", json.dumps(NOTICE))

	def test_a_user_who_cannot_read_the_doctype_is_refused(self):
		real = frappe.has_permission

		def has_permission(doctype, ptype="read", *args, **kwargs):
			if doctype == "ToDo":
				raise frappe.PermissionError
			return real(doctype, ptype, *args, **kwargs)

		with patch.object(notification_api.frappe, "has_permission", side_effect=has_permission):
			with self.assertRaises(frappe.PermissionError):
				preview_notification("", "send_email", "ToDo", json.dumps(NOTICE))

	def test_other_element_types_are_not_previewed(self):
		with self.assertRaises(frappe.ValidationError):
			preview_notification("", "startEvent", "ToDo", json.dumps(NOTICE))


TASK_ACTIONS = json.dumps([{"action": "Approve"}, {"action": "Reject", "confirmTransition": "true"}])


class TestTaskEmailPreview(FrappeTestCase):
	def setUp(self):
		clear_cache()
		self.todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "Fix the gate", "allocated_to": "Administrator"}
		).insert()

	def _preview(self, cfg):
		settings = {"taskName": "Review", "taskActions": TASK_ACTIONS, **cfg}
		with patch("one_bpmn.utils.translation.translate_cached", side_effect=lambda text: text):
			return preview_notification("", "userTask", "ToDo", json.dumps(settings))

	def test_the_card_is_rendered_for_the_latest_record_with_links_and_no_token(self):
		with (
			patch("one_bpmn.utils.token.generate_action_token") as action_token,
			patch("one_bpmn.utils.token.generate_status_token") as status_token,
			patch("one_bpmn.email_builder.fields.generate_file_token") as file_token,
			patch.object(frappe, "sendmail") as sendmail,
		):
			result = self._preview(
				{
					"notifyLayout": "card",
					"notifyAssigneeSubject": "Review {{ doc.name }}",
					"notifyQuestionEn": "Close {{ doc.description }}?",
					"notifyFacts": json.dumps(["description"]),
					"notifyAttachments": "true",
				}
			)

		self.assertEqual(result["docname"], self.todo.name)
		self.assertEqual(result["subject"], f"Review {self.todo.name}")
		html = result["html"]
		self.assertIn("Close Fix the gate?", html)
		self.assertIn('class="facts"', html)
		self.assertIn(
			f'href="{frappe.utils.get_url()}/app/todo/{self.todo.name}" target="_blank">Approve</a>', html
		)
		self.assertNotIn("<button", html)
		self.assertNotIn("token=", html)
		for mock in (action_token, status_token, file_token, sendmail):
			mock.assert_not_called()

	def test_html_mode_renders_todays_body_with_the_actions_as_links(self):
		result = self._preview(
			{
				"notifyLayout": "html",
				"notifyAssigneeSubject": "Review {{ doc.name }}",
				"notifyAssigneeBody": "<p>Please look at {{ doc.description }}</p>",
			}
		)

		html = result["html"]
		self.assertIn("Please look at Fix the gate", html)
		self.assertRegex(html, r"<a href=\"[^\"]+/app/todo/[^\"]+\"[^>]*>\s*Approve\s*</a>")
		self.assertRegex(html, r">\s*Reject\s*</a>")
		self.assertNotIn("Close Fix the gate?", html)
