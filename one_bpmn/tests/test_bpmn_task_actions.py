"""Unit tests for :mod:`one_bpmn.api.bpmn_task_actions`.

Tests the AMP action callback endpoint.

Since ``handle_amp_action`` uses ``@frappe.whitelist`` and requires
``frappe.local.response``, these tests must run inside a Frappe site
context — either via ``bench run-tests`` or with ``frappe.init``/``frappe.connect``.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_bpmn_task_actions
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

_TEST_SECRET = "test-secret-key-for-unit-tests"


def _mock_secret():
	"""Context manager to mock the HMAC secret."""
	return patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET)


def _make_token(
	instance_name: str = "INST-001",
	task_id: str = "task-uuid",
	action: str = "Approve",
	user: str = "user@test.com",
	expiry_hours: int = 72,
) -> str:
	"""Generate a valid token for testing."""
	with _mock_secret():
		from one_bpmn.utils.token import generate_action_token
		return generate_action_token(instance_name, task_id, action, user, expiry_hours)


def _make_expired_token() -> str:
	"""Generate a token that has already expired."""
	with _mock_secret():
		from one_bpmn.utils.token import _sign
		payload = {
			"action": "Approve",
			"expires": int(time.time()) - 3600,
			"instance_name": "INST-001",
			"task_id": "task-uuid",
			"user": "user@test.com",
		}
		payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		return f"{payload_json}.{_sign(payload_json)}"


def _setup_request(method="POST", origin="https://mail.google.com", source_origin=None):
	"""Set up a fake Frappe request context."""
	frappe.local.request = MagicMock()
	frappe.local.request.method = method
	frappe.local.request.headers = {"Origin": origin}
	frappe.local.request.args = {}
	if source_origin:
		frappe.local.request.args["__amp_source_origin"] = source_origin
	# Reset response headers
	frappe.local.response.headers = {}


class TestHandleAmpAction(FrappeTestCase):
	"""Tests for :func:`handle_amp_action`."""

	def test_valid_action_completes(self):
		"""Valid token + complete_task success → 200 with success message."""
		_setup_request(source_origin="user@test.com")
		token = _make_token()

		with _mock_secret():
			with patch("one_bpmn.api.instance_api.complete_task") as mock_ct:
				mock_ct.return_value = {"instance": "INST-001", "status": "Running", "active_tasks": []}
				with patch.object(frappe, "set_user"):
					from one_bpmn.api.bpmn_task_actions import handle_amp_action
					result = handle_amp_action(token=token)

		self.assertIn("message", result)
		self.assertIn("Approve", result["message"])

	def test_tampered_token_returns_error(self):
		"""Tampered token → error response."""
		_setup_request()

		with _mock_secret():
			from one_bpmn.api.bpmn_task_actions import handle_amp_action
			result = handle_amp_action(token="tampered.XXXX")

		self.assertIn("error", result)

	def test_expired_token_returns_error(self):
		"""Expired token → error response."""
		_setup_request()
		token = _make_expired_token()

		with _mock_secret():
			from one_bpmn.api.bpmn_task_actions import handle_amp_action
			result = handle_amp_action(token=token)

		self.assertIn("error", result)

	def test_already_actioned_returns_friendly(self):
		"""Task already completed → 'already actioned' message."""
		_setup_request()
		token = _make_token()

		with _mock_secret():
			with patch("one_bpmn.api.instance_api.complete_task") as mock_ct:
				mock_ct.side_effect = frappe.ValidationError(
					"Task 'task-uuid' not found in the active tasks of this instance."
				)
				with patch.object(frappe, "set_user"):
					from one_bpmn.api.bpmn_task_actions import handle_amp_action
					result = handle_amp_action(token=token)

		self.assertIn("message", result)
		self.assertIn("already", result["message"].lower())

	def test_cors_headers_set(self):
		"""Response includes AMP CORS headers."""
		_setup_request(source_origin="user@test.com")
		token = _make_token()

		with _mock_secret():
			with patch("one_bpmn.api.instance_api.complete_task") as mock_ct:
				mock_ct.return_value = {"instance": "INST-001", "status": "Running", "active_tasks": []}
				with patch.object(frappe, "set_user"):
					from one_bpmn.api.bpmn_task_actions import handle_amp_action
					handle_amp_action(token=token)

		headers = frappe.local.response.headers
		self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://mail.google.com")
		self.assertIn("AMP-Access-Control-Allow-Source-Origin", headers)

	def test_options_preflight(self):
		"""OPTIONS request returns CORS headers."""
		_setup_request(method="OPTIONS")

		from one_bpmn.api.bpmn_task_actions import handle_amp_action
		handle_amp_action()

		headers = frappe.local.response.headers
		self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://mail.google.com")
		self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))

	def test_amp_source_origin_echoed(self):
		"""__amp_source_origin query param is echoed in response header."""
		_setup_request(method="OPTIONS", source_origin="sender@one-fm.com")

		from one_bpmn.api.bpmn_task_actions import handle_amp_action
		handle_amp_action()

		headers = frappe.local.response.headers
		self.assertEqual(headers.get("AMP-Access-Control-Allow-Source-Origin"), "sender@one-fm.com")
