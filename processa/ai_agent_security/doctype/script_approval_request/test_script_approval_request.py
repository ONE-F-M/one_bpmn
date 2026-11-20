# Copyright (c) 2026, one-fm and contributors

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_categories import clear_category_cache
from processa.ai_agent_security.code_checks.script_gate import script_task_findings
from processa.patches.v1_0 import seed_script_import_categories

PROCESS = "Approval Test Process"
OTHER_PROCESS = "Approval Test Other Process"
SCRIPT = "Approval Test Script"
TASK = "Activity_fetch"
OUTSIDER = "approval-outsider@example.com"


class TestScriptApprovalRequest(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()
		for process in (PROCESS, OTHER_PROCESS):
			if not frappe.db.exists("Process", process):
				frappe.get_doc(
					{
						"doctype": "Process",
						"process_name": process,
						"description": process,
						"process_owner": "Administrator",
					}
				).insert()
		self._script("import requests\nresult['ok'] = 1")
		if not frappe.db.exists("User", OUTSIDER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": OUTSIDER,
					"first_name": "Outsider",
					"send_welcome_email": 0,
					"roles": [{"role": "Blogger"}],
				}
			).insert()
		settings = frappe.get_doc("Processa Settings")
		settings.script_security_reviewer = "Administrator"
		settings.script_security_approver = "Administrator"
		settings.save()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _script(self, body):
		if frappe.db.exists("Server Script", SCRIPT):
			frappe.db.set_value("Server Script", SCRIPT, "script", body)
			return
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT,
				"script_type": "API",
				"api_method": "approval_test_script",
				"script": body,
			}
		).insert()

	def _request(self, process=PROCESS, task=TASK, **values):
		return frappe.get_doc(
			{
				"doctype": "Script Approval Request",
				"process_name": process,
				"script_task": task,
				"server_script": SCRIPT,
				"reason": "Fetches the rates",
				**values,
			}
		).insert()

	def _approved(self, process=PROCESS, task=TASK):
		request = self._request(process, task)
		request.db_set("status", "Approved")
		return request

	def _flagged(self, process=PROCESS, task=TASK):
		code = frappe.db.get_value("Server Script", SCRIPT, "script")
		return [f["name"] for f in script_task_findings(code, process, task, SCRIPT)]

	def test_a_script_task_with_no_request_is_flagged(self):
		self.assertEqual(self._flagged(), ["requests"])

	def test_an_approved_request_clears_what_it_lists(self):
		self._approved()
		self.assertEqual(self._flagged(), [])

	def test_a_name_added_after_approval_is_flagged(self):
		self._approved()
		self._script("import requests\nimport socket\nresult['ok'] = 1")
		self.assertEqual(self._flagged(), ["socket"])

	def test_an_approval_does_not_carry_to_another_process(self):
		self._approved()
		self.assertEqual(self._flagged(process=OTHER_PROCESS), ["requests"])

	def test_requests_that_are_not_approved_clear_nothing(self):
		for status in ("Pending Review", "Pending Approval", "Rejected"):
			with self.subTest(status=status):
				request = self._request()
				request.db_set("status", status)
				self.assertEqual(self._flagged(), ["requests"])
				request.db_set("status", "Rejected")

	def test_items_script_and_people_are_set_on_the_server(self):
		request = self._request(
			status="Approved",
			requested_items=[{"category": "Python basics", "item_name": "json", "lines": "9"}],
			script_at_time_of_request="x = 1",
			approver="Guest",
		)
		self.assertEqual(request.status, "Pending Review")
		self.assertEqual(
			[(d.category, d.item_name, d.lines) for d in request.requested_items],
			[("Network", "requests", "1")],
		)
		self.assertEqual(request.script_at_time_of_request, "import requests\nresult['ok'] = 1")
		self.assertEqual((request.reviewer, request.approver), ("Administrator", "Administrator"))
		self.assertEqual(request.requested_by, "Administrator")

	def test_a_second_open_request_is_refused(self):
		first = self._request()
		with self.assertRaises(frappe.ValidationError) as caught:
			self._request()
		self.assertIn(first.name, str(caught.exception))

	def test_a_script_task_with_nothing_flagged_is_refused(self):
		self._script("import json\nresult['ok'] = 1")
		with self.assertRaises(frappe.ValidationError) as caught:
			self._request()
		self.assertIn("nothing that needs approval", str(caught.exception))

	def test_a_user_who_cannot_read_the_script_gets_a_permission_error(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			self._request()

	def test_the_requester_reads_their_own_request_and_others_do_not(self):
		request = self._request()
		request.db_set("requested_by", OUTSIDER)
		request.db_set({"reviewer": None, "approver": None})
		self.assertTrue(frappe.has_permission("Script Approval Request", "read", request.name, user=OUTSIDER))
		request.db_set("requested_by", "Administrator")
		self.assertFalse(
			frappe.has_permission("Script Approval Request", "read", request.name, user=OUTSIDER)
		)

	def test_the_approver_must_be_an_application_manager(self):
		settings = frappe.get_doc("Processa Settings")
		settings.script_security_approver = OUTSIDER
		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_a_new_map_version_keeps_the_approval_while_task_and_script_match(self):
		self._approved()
		self.assertEqual(self._flagged(task=TASK), [])
		self.assertEqual(self._flagged(task="Activity_renamed"), ["requests"])
