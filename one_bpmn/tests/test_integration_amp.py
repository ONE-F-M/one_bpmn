"""Integration tests for AMP email infrastructure.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_integration_amp
"""
from __future__ import annotations

import json
import time
from email import policy
from email.parser import Parser
from unittest.mock import patch, MagicMock

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAmpEmailIntegration(FrappeTestCase):
	"""Integration tests verifying the full AMP email pipeline."""

	def test_email_queue_has_amp_html_field(self):
		"""The amp_html custom field exists on Email Queue."""
		meta = frappe.get_meta("Email Queue")
		field = meta.get_field("amp_html")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Long Text")

	def test_amp_mime_injection(self):
		"""Email with amp_html flag gets 3 MIME parts in correct order."""
		amp_content = '<!doctype html><html ⚡4email><head><meta charset="utf-8"><script async src="https://cdn.ampproject.org/v0.js"></script><style amp4email-boilerplate>body{visibility:hidden}</style></head><body><p>Test</p></body></html>'

		frappe.flags.amp_html = amp_content
		frappe.sendmail(
			recipients=["test@example.com"],
			subject="AMP Integration Test",
			message="<p>Test body</p>",
			now=False,
		)

		# Get the email queue entry
		eq = frappe.get_all("Email Queue", order_by="creation desc", limit=1, fields=["name"])
		self.assertTrue(len(eq) > 0)

		doc = frappe.get_doc("Email Queue", eq[0].name)

		# Parse MIME
		msg = Parser(policy=policy.SMTP).parsestr(doc.message)
		for part in msg.walk():
			if part.get_content_type() == "multipart/alternative":
				types = [p.get_content_type() for p in part.get_payload()]
				self.assertEqual(types, ["text/plain", "text/x-amp-html", "text/html"])
				break
		else:
			self.fail("No multipart/alternative found in MIME")

		# Cleanup
		frappe.delete_doc("Email Queue", doc.name, force=True)

	def test_amp_html_stored_on_row(self):
		"""The amp_html custom field is populated on the Email Queue row."""
		amp_content = '<html ⚡4email><body><p>Stored Test</p></body></html>'

		frappe.flags.amp_html = amp_content
		frappe.sendmail(
			recipients=["test@example.com"],
			subject="AMP Storage Test",
			message="<p>Test</p>",
			now=False,
		)

		eq = frappe.get_all("Email Queue", order_by="creation desc", limit=1, fields=["name"])
		doc = frappe.get_doc("Email Queue", eq[0].name)
		self.assertEqual(doc.amp_html, amp_content)

		# Cleanup
		frappe.delete_doc("Email Queue", doc.name, force=True)

	def test_token_roundtrip_with_site_key(self):
		"""Token generation and verification work with the real site key."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-TEST", "task-test", "Approve", "admin@test.com")
		payload = verify_action_token(token)

		self.assertEqual(payload["instance_name"], "INST-TEST")
		self.assertEqual(payload["action"], "Approve")
		self.assertEqual(payload["user"], "admin@test.com")

	def test_stale_token_rejected(self):
		"""Expired token raises ValidationError."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token, _sign

		# Create an expired token
		payload = {
			"action": "Approve",
			"expires": int(time.time()) - 3600,
			"instance_name": "INST-TEST",
			"task_id": "task-test",
			"user": "admin@test.com",
		}
		payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		token = f"{payload_json}.{_sign(payload_json)}"

		with self.assertRaises(frappe.ValidationError):
			verify_action_token(token)

	def test_tampered_token_rejected(self):
		"""Tampered token raises AuthenticationError."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-TEST", "task-test", "Approve", "admin@test.com")
		tampered = token[:-4] + "XXXX"

		with self.assertRaises(frappe.AuthenticationError):
			verify_action_token(tampered)
