# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""On a Production site, import and deploy warn about notifications that send from another address."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _check_notification_senders
from one_bpmn.api.process_map_api import validate_bpmn_readiness

NOTIFICATIONS = "Processa Test Notifications"
STAGING = "Processa Test Staging"
NOTIFY_ADDRESS = "processa-notify@example.com"
STAGING_ADDRESS = "processa-staging@example.com"

MAP = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="sender_readiness" isExecutable="true">
		<bpmn:startEvent id="Start" />
		<bpmn:serviceTask id="Activity_mail" name="Notify HR" spiffworkflow:serviceType="send_email"
			spiffworkflow:emailAccount="Processa Test Staging" spiffworkflow:emailToRoles="HR Manager"
			spiffworkflow:emailSubject="Hi" spiffworkflow:emailBody="Body" />
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""


def _send_email(account: str) -> dict:
	return {"serviceType": "send_email", "emailAccount": account}


class TestNotificationSenderWarning(FrappeTestCase):
	def setUp(self):
		for name, address in ((NOTIFICATIONS, NOTIFY_ADDRESS), (STAGING, STAGING_ADDRESS)):
			if not frappe.db.exists("Email Account", name):
				frappe.get_doc(
					{"doctype": "Email Account", "name": name, "email_account_name": name, "email_id": address}
				).db_insert()
		frappe.db.set_single_value("Processa Settings", "production_notification_account", NOTIFICATIONS)

	def _details(self, instance_type: str = "Production", service=None, user=None) -> list:
		with patch("one_bpmn.api.editability.get_instance_type", return_value=instance_type):
			return [w["detail"] for w in _check_notification_senders(service or {}, user or {})]

	def test_a_send_email_task_using_another_address_is_flagged_on_production(self):
		details = self._details(service={"Activity_mail": _send_email(STAGING)})

		self.assertEqual(len(details), 1)
		self.assertIn("'Activity_mail' sends from processa-staging@example.com", details[0])
		self.assertIn("should send from processa-notify@example.com", details[0])

	def test_the_configured_address_is_not_flagged(self):
		self.assertEqual(self._details(service={"Activity_mail": _send_email(NOTIFICATIONS)}), [])

	def test_a_notifying_user_task_is_checked_and_a_silent_one_is_not(self):
		user = {
			"Activity_review": {"notifyAssignee": "true", "notifyAssigneeAccount": STAGING},
			"Activity_quiet": {"notifyAssignee": "false", "notifyAssigneeAccount": STAGING},
		}

		details = self._details(user=user)

		self.assertEqual(len(details), 1)
		self.assertIn("'Activity_review'", details[0])

	def test_the_address_comes_from_processa_settings(self):
		frappe.db.set_single_value("Processa Settings", "production_notification_account", STAGING)
		service = {"Activity_staging": _send_email(STAGING), "Activity_notify": _send_email(NOTIFICATIONS)}

		details = self._details(service=service)

		self.assertEqual(len(details), 1)
		self.assertIn("'Activity_notify' sends from processa-notify@example.com", details[0])

	def test_nothing_is_flagged_when_no_account_is_set(self):
		frappe.db.set_single_value("Processa Settings", "production_notification_account", None)

		self.assertEqual(self._details(service={"Activity_mail": _send_email(STAGING)}), [])

	def test_nothing_is_flagged_off_production(self):
		for instance_type in ("Local", "Staging", "BA"):
			self.assertEqual(self._details(instance_type, service={"Activity_mail": _send_email(STAGING)}), [])

	def test_the_readiness_check_lists_the_step_by_name_without_blocking(self):
		with patch("one_bpmn.api.editability.get_instance_type", return_value="Production"):
			result = validate_bpmn_readiness(MAP)

		sender = next(c for c in result["categories"] if c["label"] == "Notification Sender")
		self.assertEqual(sender["items"][0]["name"], "Notify HR")
		self.assertEqual(sender["items"][0]["type"], "warning")
		self.assertIn("processa-staging@example.com", sender["items"][0]["detail"])
		self.assertTrue(result["all_ready"])
