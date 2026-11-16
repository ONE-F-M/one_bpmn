"""The sandbox reports the apps it holds; Processa accepts those apps and their repository names for a dispatch."""

from __future__ import annotations

import json
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from processa.agents_sandbox.sandbox import apps, ops

REPORT = [
	{"app": "one_fm_password_management", "repository": "ONE-F-M/password_management"},
	{"app": "agent_sandbox", "repository": "ONE-F-M/agent-sandbox"},
	{"app": "processa", "repository": "ONE-F-M/processa"},
]


class TestCleanReport(FrappeTestCase):
	def test_good_entries_are_kept_and_bad_ones_dropped(self):
		report = [
			*REPORT,
			{"app": "agent_sandbox", "repository": "ONE-F-M/agent-sandbox"},  # a duplicate
			{"app": "bad-name", "repository": ""},
			{"app": "../etc", "repository": ""},
			{"app": "odd_repo", "repository": "not a repository"},
			{"app": "no_remote", "repository": ""},
			"not a dict",
			{"repository": "ONE-F-M/x"},
		]
		self.assertEqual(apps.clean(report), [*REPORT, {"app": "no_remote", "repository": ""}])

	def test_anything_but_a_list_is_nothing(self):
		for report in (None, {}, "x", 5):
			self.assertEqual(apps.clean(report), [])

	def test_a_report_is_capped(self):
		many = [{"app": f"app_{i}", "repository": ""} for i in range(apps.MAX_APPS + 20)]
		self.assertEqual(len(apps.clean(many)), apps.MAX_APPS)


class TestRecordAndRead(FrappeTestCase):
	def test_a_report_is_stored_with_the_time_it_arrived(self):
		with patch.object(apps.frappe.db, "set_single_value") as write, patch.object(apps.frappe.utils, "now", return_value="NOW"):
			self.assertEqual(apps.record(REPORT), 3)
		self.assertEqual(
			[(c.args[1], c.args[2]) for c in write.call_args_list],
			[("sandbox_reported_apps", json.dumps(REPORT)), ("sandbox_reported_apps_at", "NOW")],
		)

	def test_an_empty_or_unusable_report_keeps_the_last_good_one(self):
		for report in ([], None, [{"app": "bad-name"}], "x"):
			with patch.object(apps.frappe.db, "set_single_value") as write:
				self.assertEqual(apps.record(report), 0)
			write.assert_not_called()

	def test_the_stored_report_is_read_back_and_a_damaged_one_is_nothing(self):
		with patch.object(apps.frappe.db, "get_single_value", return_value=json.dumps(REPORT)):
			self.assertEqual(apps.app_names(), ["one_fm_password_management", "agent_sandbox", "processa"])
			self.assertEqual(apps.repository_names(), ["password_management", "agent-sandbox", "processa"])
		for stored in ("{not json", None, ""):
			with patch.object(apps.frappe.db, "get_single_value", return_value=stored):
				self.assertEqual(apps.reported(), [])


class TestDispatchCheck(FrappeTestCase):
	def _with_report(self, report):
		return (
			patch.object(apps.frappe.db, "get_single_value", return_value=json.dumps(report)),
			patch.object(ops.frappe, "get_installed_apps", return_value=["frappe", "processa"]),
			patch.object(ops, "_missing_branch_error", return_value=None),
		)

	def test_the_dropdown_lists_the_reported_apps_once_and_not_the_repository_names(self):
		a, b, c = self._with_report(REPORT)
		with a, b, c:
			choices = ops.target_app_choices()
		self.assertEqual(choices.count("processa"), 1)
		self.assertIn("agent_sandbox", choices)
		self.assertIn("mobile_app_ionic", choices)  # the fixed list is still there
		self.assertNotIn("password_management", choices)
		self.assertNotIn("agent-sandbox", choices)

	def test_a_dispatch_may_name_a_reported_app_or_its_repository(self):
		a, b, c = self._with_report(REPORT)
		with a, b, c:
			for name in ("agent_sandbox", "agent-sandbox", "password_management", "one_fm_password_management", "processa"):
				self.assertIsNone(ops.dispatch_error(name, "staging"), name)

	def test_an_app_the_sandbox_never_reported_is_refused_and_the_message_lists_what_it_has(self):
		a, b, c = self._with_report(REPORT)
		with a, b, c:
			error = ops.dispatch_error("press", "staging")
		self.assertIn("'press' is not an app the sandbox has", error)
		self.assertIn("agent-sandbox", error)

	def test_before_any_report_the_fixed_lists_still_apply(self):
		a, b, c = self._with_report([])
		with a, b, c:
			self.assertIsNone(ops.dispatch_error("mobile_app_ionic", "staging"))
			self.assertIsNotNone(ops.dispatch_error("agent-sandbox", "staging"))


class TestRegisterCall(FrappeTestCase):
	def test_the_apps_in_the_register_call_reach_the_session_module(self):
		from processa.api import sandbox_session

		body = {"session": "S-1", "token": "t", "apps": REPORT}
		with patch.object(sandbox_session, "_body", return_value=body), patch.object(sandbox_session.sessions, "register", return_value={"session_key": "k"}) as register:
			answer = sandbox_session.register()
		register.assert_called_once_with("S-1", "t", REPORT)
		self.assertTrue(answer["accepted"])
