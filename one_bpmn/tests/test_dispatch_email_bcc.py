"""Tests for BCC handling in dispatch_email and composer._send_email.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_dispatch_email_bcc
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_email


def _instance():
	return frappe._dict(
		{
			"name": "INST-BCC",
			"doctype": "BPMN Process Instance",
			"context_doctype": None,
			"context_docname": None,
		}
	)


def _cfg(**extra):
	return {"emailTo": "to@one-fm.com", "emailCc": "cc@one-fm.com", "emailSubject": "Hello", **extra}


class TestDispatchEmailBcc(FrappeTestCase):
	def _run(self, task_cfg):
		with patch("one_bpmn.email_builder.composer.compose_and_send_info_email", return_value=""), patch(
			"one_bpmn.email_builder.composer.frappe.sendmail"
		) as sendmail:
			dispatch_email(_instance(), None, task_cfg)
		return sendmail

	def test_bcc_is_trimmed_and_blanks_dropped(self):
		sendmail = self._run(_cfg(emailBcc=" a@one-fm.com ,, b@one-fm.com , "))
		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["bcc"], ["a@one-fm.com", "b@one-fm.com"])
		self.assertEqual(kwargs["recipients"], ["to@one-fm.com"])
		self.assertEqual(kwargs["cc"], "cc@one-fm.com")

	def test_empty_or_missing_bcc_sends_no_bcc(self):
		for cfg in (_cfg(emailBcc=""), _cfg(emailBcc="  "), _cfg(emailBcc=" , "), _cfg(emailBcc=None), _cfg()):
			self.assertIsNone(self._run(cfg).call_args.kwargs["bcc"])
