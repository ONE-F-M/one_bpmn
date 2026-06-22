"""Regression guard — non-BPMN emails must remain unchanged.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_regression_no_amp
"""
from __future__ import annotations

from email import policy
from email.parser import Parser

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRegressionNoAmp(FrappeTestCase):
	"""Ensure normal (non-AMP) emails are 100% unchanged."""

	def test_normal_email_no_amp_field(self):
		"""Standard email without frappe.flags.amp_html has no amp_html value."""
		# Ensure flag is NOT set
		frappe.flags.amp_html = None

		frappe.sendmail(
			recipients=["test@example.com"],
			subject="Normal Email Test",
			message="<p>This is a normal email</p>",
			now=False,
		)

		eq = frappe.get_all("Email Queue", order_by="creation desc", limit=1, fields=["name"])
		self.assertTrue(len(eq) > 0)

		doc = frappe.get_doc("Email Queue", eq[0].name)
		self.assertFalse(doc.amp_html)  # None or empty

		# Cleanup
		frappe.delete_doc("Email Queue", doc.name, force=True)

	def test_normal_email_no_amp_mime(self):
		"""Standard email does NOT contain text/x-amp-html MIME part."""
		frappe.flags.amp_html = None

		frappe.sendmail(
			recipients=["test@example.com"],
			subject="No AMP MIME Test",
			message="<p>Standard email</p>",
			now=False,
		)

		eq = frappe.get_all("Email Queue", order_by="creation desc", limit=1, fields=["name"])
		doc = frappe.get_doc("Email Queue", eq[0].name)

		self.assertNotIn("text/x-amp-html", doc.message)

		# Cleanup
		frappe.delete_doc("Email Queue", doc.name, force=True)

	def test_normal_email_structure_unchanged(self):
		"""Standard email has only text/plain + text/html (standard 2-part structure)."""
		frappe.flags.amp_html = None

		frappe.sendmail(
			recipients=["test@example.com"],
			subject="Structure Test",
			message="<p>Normal structure</p>",
			now=False,
		)

		eq = frappe.get_all("Email Queue", order_by="creation desc", limit=1, fields=["name"])
		doc = frappe.get_doc("Email Queue", eq[0].name)

		msg = Parser(policy=policy.SMTP).parsestr(doc.message)
		for part in msg.walk():
			if part.get_content_type() == "multipart/alternative":
				types = [p.get_content_type() for p in part.get_payload()]
				# Should only be 2 parts: plain + html
				self.assertEqual(len(types), 2)
				self.assertIn("text/plain", types)
				self.assertIn("text/html", types)
				self.assertNotIn("text/x-amp-html", types)
				break

		# Cleanup
		frappe.delete_doc("Email Queue", doc.name, force=True)
