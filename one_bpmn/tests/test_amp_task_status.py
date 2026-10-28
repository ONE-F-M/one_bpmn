"""Tests for :func:`one_bpmn.api.todo_actions.get_amp_task_status`.

Database reads are mocked, so no BPMN Process Instance is needed.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_amp_task_status
"""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

_TEST_SECRET = "test-secret-key-for-unit-tests"
_CONTEXT = frappe._dict(context_doctype="ToDo", context_docname="TODO-1")


def _expired(token: str) -> str:
	"""Re-sign the token's payload with an expiry in the past."""
	from one_bpmn.utils.token import _sign

	payload = json.loads(base64.urlsafe_b64decode(token.rsplit(".", 1)[0].encode("ascii")))
	payload["expires"] = int(time.time()) - 3600
	payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
	return f"{encoded}.{_sign(payload_json)}"


class TestGetAmpTaskStatus(FrappeTestCase):
	def setUp(self):
		frappe.clear_cache(doctype="ToDo")

		for patcher in (
			patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET),
			patch("frappe.utils.get_fullname", side_effect=lambda user: f"Name of {user}"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

		cors_patcher = patch("one_bpmn.api.todo_actions._set_amp_cors_headers")
		self.cors = cors_patcher.start()
		self.addCleanup(cors_patcher.stop)

		self.task_row = None
		self.workflow_name = None
		self.db_calls = []

	def _call(self, token):
		from one_bpmn.api.todo_actions import get_amp_task_status

		real_get_value = frappe.db.get_value

		def fake_get_value(doctype, filters=None, fieldname=None, *args, **kwargs):
			self.db_calls.append(doctype)
			if doctype == "BPMN Active Task":
				return self.task_row
			if doctype == "BPMN Process Instance":
				return _CONTEXT
			if doctype == "Workflow State":
				return "Success"
			if doctype == "ToDo" and fieldname in ("workflow_state", "status"):
				return "Approved" if fieldname == "workflow_state" else "Open"
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with (
			patch("frappe.db.get_value", side_effect=fake_get_value),
			patch("frappe.model.workflow.get_workflow_name", return_value=self.workflow_name),
			patch("frappe.model.workflow.get_workflow_state_field", return_value="workflow_state"),
		):
			result = get_amp_task_status(token)

		self.assertEqual(list(result), ["items"])
		self.assertEqual(len(result["items"]), 1)
		self.cors.assert_called()
		return result["items"][0]

	def _row(self, status, assigned_user="user@test.com"):
		return frappe._dict(
			status=status,
			task_name="Approve Leave",
			assigned_user=assigned_user,
			end_time=None,
			modified="2026-01-05 10:30:00",
		)

	def test_waiting_valid_token(self):
		from one_bpmn.utils.token import generate_status_token

		self.task_row = self._row("Waiting")
		item = self._call(generate_status_token("INST-1", "t1", user="user@test.com"))
		self.assertTrue(item["is_waiting"])
		self.assertFalse(item["is_expired"])
		self.assertFalse(item["is_reassigned"])

	def test_expired_waiting(self):
		from one_bpmn.utils.token import generate_status_token

		self.task_row = self._row("Waiting")
		item = self._call(_expired(generate_status_token("INST-1", "t1", user="user@test.com")))
		self.assertTrue(item["is_expired"])
		self.assertFalse(item["is_waiting"])

	def test_expired_completed(self):
		from one_bpmn.utils.token import generate_status_token

		self.task_row = self._row("Completed")
		self.workflow_name = "Leave Flow"
		item = self._call(_expired(generate_status_token("INST-1", "t1", user="user@test.com")))
		self.assertFalse(item["is_expired"])
		self.assertTrue(item["is_completed"])
		self.assertFalse(item["is_waiting"])
		self.assertEqual(item["completed_by"], "Name of user@test.com")
		self.assertEqual(item["action_taken"], "Approve Leave")
		self.assertTrue(item["completed_at"])
		self.assertEqual(item["workflow_state"], "Approved")

	def test_tampered(self):
		from one_bpmn.utils.token import generate_status_token

		item = self._call(generate_status_token("INST-1", "t1")[:-4] + "XXXX")
		self.assertTrue(item["is_expired"])
		self.assertFalse(item["is_waiting"])
		self.assertFalse(item["is_completed"])
		self.assertNotIn("workflow_state", item)
		self.assertEqual(self.db_calls, [])

	def test_malformed_and_missing(self):
		for token in ("", "not-a-token", "abc.def"):
			item = self._call(token)
			self.assertTrue(item["is_expired"])
			self.assertNotIn("workflow_state", item)
		self.assertEqual(self.db_calls, [])

	def test_not_a_status_token(self):
		from one_bpmn.utils.token import generate_action_token

		item = self._call(generate_action_token("INST-1", "t1", "Approve", "user@test.com"))
		self.assertTrue(item["is_expired"])
		self.assertFalse(item["is_waiting"])
		self.assertEqual(self.db_calls, [])

	def test_reassigned(self):
		from one_bpmn.utils.token import generate_status_token

		self.task_row = self._row("Waiting", assigned_user="other@test.com")
		item = self._call(generate_status_token("INST-1", "t1", user="user@test.com"))
		self.assertTrue(item["is_reassigned"])
		self.assertEqual(item["assigned_to"], "Name of other@test.com")
		self.assertFalse(item["is_waiting"])
		self.assertFalse(item["is_expired"])

	def test_doc_only_token(self):
		from one_bpmn.utils.token import generate_status_token

		self.workflow_name = "Leave Flow"
		item = self._call(generate_status_token("INST-1"))
		self.assertEqual(item["workflow_state"], "Approved")
		self.assertEqual(item["workflow_state_style"], "Success")
		self.assertFalse(item["is_waiting"])
		self.assertFalse(item["is_completed"])
		self.assertFalse(item["is_expired"])
		self.assertNotIn("completed_by", item)
		self.assertNotIn("BPMN Active Task", self.db_calls)

	def test_workflow_style_present(self):
		from one_bpmn.utils.token import generate_status_token

		self.task_row = self._row("Completed")
		self.workflow_name = "Leave Flow"
		item = self._call(generate_status_token("INST-1", "t1"))
		self.assertEqual(item["workflow_state"], "Approved")
		self.assertEqual(item["workflow_state_style"], "Success")

	def test_workflow_style_absent(self):
		from one_bpmn.utils.token import generate_status_token

		self.task_row = self._row("Completed")
		self.workflow_name = None
		item = self._call(generate_status_token("INST-1", "t1"))
		self.assertEqual(item["workflow_state"], "")
		self.assertEqual(item["workflow_state_style"], "")
