# Copyright (c) 2026, one-fm and contributors
# WI-001494 follow-up: inline engine passes must never poison the session.
#
# frappe.set_user() rewrites local.session.sid and WIPES session.data. In a
# background worker that is fine; inside a web request the end-of-request
# session persistence writes the gutted data back under the browser's cookie
# sid, and every following request fails with "User None is disabled".
#
# Since WI-001494/WI-001496 run start_queued_instance and _complete_task_job
# INLINE in the request, both must call set_user ONLY when the identity
# actually differs (the background-job case).

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["BPMN Process Model"]


class TestInlineSessionSafety(FrappeTestCase):
	def _bare_instance(self, status):
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"test-{frappe.generate_hash(length=6)}",
				"status": status,
			}
		)
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)
		return instance

	def test_complete_task_job_skips_set_user_for_current_user(self):
		from one_bpmn.api import instance_api

		instance = self._bare_instance("Active")
		with patch.object(frappe, "set_user") as set_user:
			# advance() fails on the bogus task id — caught inside the job.
			instance_api._complete_task_job(
				instance_name=instance.name,
				task_id="no-such-task",
				run_as_user=frappe.session.user,
			)
		set_user.assert_not_called()

	def test_complete_task_job_switches_for_different_user(self):
		from one_bpmn.api import instance_api

		instance = self._bare_instance("Active")
		with patch.object(frappe, "set_user") as set_user:
			instance_api._complete_task_job(
				instance_name=instance.name,
				task_id="no-such-task",
				run_as_user="someone.else@one-fm.com",
			)
		set_user.assert_called_once_with("someone.else@one-fm.com")

	def test_start_queued_instance_skips_set_user_for_current_user(self):
		from one_bpmn.one_bpmn import trigger

		instance = self._bare_instance("Queued")
		with patch.object(frappe, "set_user") as set_user:
			# start() fails on the missing model — caught inside (→ Errored).
			trigger.start_queued_instance(instance.name, run_as_user=frappe.session.user)
		set_user.assert_not_called()

	def test_both_entry_points_guard_in_source(self):
		# The guard must survive refactors: no bare `if run_as_user:` before a
		# set_user in either function.
		from one_bpmn.api import instance_api
		from one_bpmn.one_bpmn import trigger

		for module, func in (
			(trigger, "def start_queued_instance"),
			(instance_api, "def _complete_task_job"),
		):
			source = open(module.__file__.replace(".pyc", ".py")).read()
			body = source[source.index(func) :]
			body = body[: body.index("\ndef ")]
			self.assertIn(
				"run_as_user != frappe.session.user",
				body,
				f"{func} lost the session-safety guard on set_user",
			)
