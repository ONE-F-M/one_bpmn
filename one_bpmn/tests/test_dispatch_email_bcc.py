"""Tests for BCC handling in dispatch_email and composer._send_email.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_dispatch_email_bcc
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

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
	def _run_one_fm(self, task_cfg):
		fake_proc = types.ModuleType("one_fm.processor")
		fake_proc.sendemail = MagicMock()
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")
		with patch.dict(sys.modules, {"one_fm": fake_root, "one_fm.processor": fake_proc}), patch(
			"one_bpmn.email_builder.composer.compose_and_send_info_email", return_value=""
		):
			dispatch_email(_instance(), None, task_cfg)
		return fake_proc.sendemail

	def _run_fallback(self, task_cfg):
		with patch.dict(sys.modules, {"one_fm": None, "one_fm.processor": None}), patch(
			"one_bpmn.email_builder.composer.compose_and_send_info_email", return_value=""
		), patch("one_bpmn.email_builder.composer.frappe.sendmail") as sendmail:
			dispatch_email(_instance(), None, task_cfg)
		return sendmail

	def test_bcc_is_trimmed_and_blanks_dropped_on_one_fm_path(self):
		sendemail = self._run_one_fm(_cfg(emailBcc=" a@one-fm.com ,, b@one-fm.com , "))
		sendemail.assert_called_once()
		kwargs = sendemail.call_args.kwargs
		self.assertEqual(kwargs["bcc"], ["a@one-fm.com", "b@one-fm.com"])
		self.assertEqual(kwargs["recipients"], ["to@one-fm.com"])
		self.assertEqual(kwargs["cc"], "cc@one-fm.com")

	def test_bcc_reaches_frappe_sendmail_fallback(self):
		sendmail = self._run_fallback(_cfg(emailBcc="a@one-fm.com, b@one-fm.com"))
		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["bcc"], ["a@one-fm.com", "b@one-fm.com"])
		self.assertNotIn("a@one-fm.com", kwargs["recipients"])
		self.assertEqual(kwargs["cc"], ["cc@one-fm.com"])

	def test_empty_bcc_sends_without_a_bcc_argument(self):
		for value in ("", "  ", " , ", None):
			sendemail = self._run_one_fm(_cfg(emailBcc=value))
			self.assertNotIn("bcc", sendemail.call_args.kwargs)
			sendmail = self._run_fallback(_cfg(emailBcc=value))
			self.assertNotIn("bcc", sendmail.call_args.kwargs)

	def test_missing_bcc_key_sends_without_a_bcc_argument(self):
		sendemail = self._run_one_fm(_cfg())
		self.assertNotIn("bcc", sendemail.call_args.kwargs)
