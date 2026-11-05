# Copyright (c) 2026, ONE FM and Contributors
# See license.txt

from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.utils import get_push_recipient_fields
from one_bpmn.one_bpmn.push_notification import FcmSender, send_test_push, tokens_for, users_from, users_in


def _token_source(doctype="Contact", user_field="user", token_field="company_name"):
	for fieldname, value in (
		("push_token_doctype", doctype),
		("push_token_user_field", user_field),
		("push_token_field", token_field),
	):
		frappe.db.set_single_value("Processa Settings", fieldname, value)
	frappe.clear_document_cache("Processa Settings", "Processa Settings")


class TestPushRecipients(FrappeTestCase):
	def test_value_resolves_user_id_or_email(self):
		email = frappe.db.get_value("User", "Administrator", "email")
		self.assertEqual(users_from(f"Administrator, {email}, nobody@example.com"), ["Administrator", "Administrator"])

	def test_link_path_follows_the_linked_record_user_field(self):
		calendar = frappe.get_doc(
			{"doctype": "Google Calendar", "user": "Administrator", "calendar_name": "push test"}
		)
		calendar.db_insert()
		event = frappe.new_doc("Event")
		event.google_calendar = calendar.name
		self.assertEqual(users_in(event, "google_calendar.user"), ["Administrator"])
		self.assertEqual(users_in(event, "subject.user"), [])


class TestPushTokens(FrappeTestCase):
	def test_tokens_come_from_the_configured_source(self):
		frappe.get_doc(
			{"doctype": "Contact", "first_name": "Push", "user": "Administrator", "company_name": "tok-1"}
		).insert(ignore_permissions=True)
		_token_source()
		self.assertEqual(tokens_for("Administrator"), ["tok-1"])
		self.assertEqual(tokens_for("Guest"), [])

	def test_no_token_source_means_no_tokens(self):
		_token_source(doctype="", user_field="", token_field="")
		self.assertEqual(tokens_for("Administrator"), [])

	def test_settings_refuse_a_missing_token_field(self):
		settings = frappe.get_single("Processa Settings")
		settings.update({"push_token_doctype": "Contact", "push_token_user_field": "user", "push_token_field": "nope"})
		self.assertRaises(frappe.ValidationError, settings.validate)


class TestFcmSender(FrappeTestCase):
	def test_rejection_returns_firebase_reason(self):
		sender = FcmSender.__new__(FcmSender)
		sender.url, sender.headers = "https://fcm.test", {}
		response = Mock(ok=False, status_code=404)
		response.json.return_value = {"error": {"message": "Requested entity was not found."}}
		with patch("one_bpmn.one_bpmn.push_notification.requests.post", return_value=response) as post:
			reason = sender.send("tok", "T", "B", {"n": 1})
		self.assertEqual(reason, "Requested entity was not found.")
		self.assertEqual(post.call_args.kwargs["json"]["message"]["data"], {"n": "1"})

	def test_missing_service_account_is_refused(self):
		frappe.db.set_single_value("Processa Settings", "push_service_account_json", "")
		frappe.clear_document_cache("Processa Settings", "Processa Settings")
		self.assertRaises(frappe.ValidationError, FcmSender)


class TestPushPermissions(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_test_push_needs_settings_write(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, send_test_push)

	def test_recipient_fields_need_process_model_write(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, get_push_recipient_fields, "Event")

	def test_recipient_fields_include_link_paths(self):
		fieldnames = [f["fieldname"] for f in get_push_recipient_fields("Event")]
		self.assertIn("owner", fieldnames)
		self.assertIn("google_calendar.user", fieldnames)
