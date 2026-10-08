# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Deploy warns about email steps whose recipients, subject or body are empty."""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _check_email_settings

SEND_EMAIL_FULL = {"serviceType": "send_email", "emailToRoles": "HR Manager", "emailSubject": "Hi", "emailBody": "Body"}


class TestEmailSettingsDeployWarning(FrappeTestCase):
	def _details(self, service=None, user=None):
		return [w["detail"] for w in _check_email_settings(service or {}, user or {})]

	def test_an_empty_send_email_task_is_flagged_with_everything_it_lacks(self):
		details = self._details(service={"Activity_mail": {"serviceType": "send_email"}})

		self.assertEqual(len(details), 1)
		self.assertIn("'Activity_mail'", details[0])
		self.assertIn("recipients, subject, body", details[0])

	def test_any_one_recipient_source_is_enough(self):
		for key in ("emailTo", "emailToDocFields", "emailToTableField", "emailToRoles"):
			cfg = {"serviceType": "send_email", key: "x", "emailSubject": "Hi", "emailBody": "Body"}
			self.assertEqual(self._details(service={"Activity_mail": cfg}), [], key)

	def test_a_complete_send_email_task_and_other_services_are_not_flagged(self):
		service = {"Activity_mail": SEND_EMAIL_FULL, "Activity_flow": {"serviceType": "apply_workflow"}}

		self.assertEqual(self._details(service=service), [])

	def test_a_user_task_that_notifies_with_no_subject_or_body_is_flagged(self):
		details = self._details(user={"Activity_review": {"notifyAssignee": "true", "notifyAssigneeAccount": "Ops"}})

		self.assertEqual(len(details), 1)
		self.assertIn("subject, body", details[0])

	def test_an_email_template_fills_both_subject_and_body(self):
		for key in ("notifyAssigneeTemplate", "notifyTemplate"):
			user = {"Activity_review": {"notifyAssignee": "true", key: "Task Assigned"}}
			self.assertEqual(self._details(user=user), [], key)

	def test_a_user_task_that_does_not_notify_is_not_flagged(self):
		self.assertEqual(self._details(user={"Activity_review": {"notifyAssignee": "false"}}), [])
