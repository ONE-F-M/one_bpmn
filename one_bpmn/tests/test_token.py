"""Unit tests for :mod:`one_bpmn.utils.token`.

The Frappe secret is mocked to a deterministic value.

Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_token
"""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

# A deterministic secret for reproducible test signatures
_TEST_SECRET = "test-secret-key-for-unit-tests"


def _decode_payload(token: str) -> dict:
	"""Decode the base64url-encoded payload segment of a sealed token."""
	payload_json = token.rsplit(".", 1)[0]
	payload_json = base64.urlsafe_b64decode(payload_json.encode("ascii")).decode("utf-8")
	return json.loads(payload_json)


class TestGenerateActionToken(FrappeTestCase):
	"""Tests for :func:`generate_action_token`."""

	def setUp(self):
		self._secret_patch = patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET)
		self._secret_patch.start()
		self.addCleanup(self._secret_patch.stop)

	def test_generate_returns_string(self):
		"""Token is a non-empty string with a dot separator."""
		from one_bpmn.utils.token import generate_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		self.assertIsInstance(token, str)
		self.assertTrue(len(token) > 0)
		self.assertIn(".", token)

	def test_payload_fields(self):
		"""Decoded payload contains all expected keys."""
		from one_bpmn.utils.token import generate_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		payload = _decode_payload(token)

		self.assertEqual(payload["instance_name"], "INST-001")
		self.assertEqual(payload["task_id"], "task-uuid")
		self.assertEqual(payload["action"], "Approve")
		self.assertEqual(payload["user"], "user@test.com")
		self.assertIn("expires", payload)
		self.assertGreater(payload["expires"], time.time())


class TestVerifyActionToken(FrappeTestCase):
	"""Tests for :func:`verify_action_token`."""

	def setUp(self):
		self._secret_patch = patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET)
		self._secret_patch.start()
		self.addCleanup(self._secret_patch.stop)

	def test_roundtrip(self):
		"""generate → verify returns the original payload."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		payload = verify_action_token(token)

		self.assertEqual(payload["instance_name"], "INST-001")
		self.assertEqual(payload["task_id"], "task-uuid")
		self.assertEqual(payload["action"], "Approve")
		self.assertEqual(payload["user"], "user@test.com")

	def test_tampered_token_rejected(self):
		"""Modifying any character in the token raises AuthenticationError."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")

		# Tamper with the signature (last 4 chars)
		tampered = token[:-4] + "XXXX"

		with self.assertRaises(frappe.AuthenticationError):
			verify_action_token(tampered)

	def test_expired_token_rejected(self):
		"""Token with expires in the past raises ValidationError."""
		from one_bpmn.utils.token import _sign, generate_action_token, verify_action_token

		# Generate a token that expired 1 hour ago
		token = generate_action_token(
			"INST-001", "task-uuid", "Approve", "user@test.com",
			expiry_hours=0,
		)
		payload = _decode_payload(token)
		payload["expires"] = int(time.time()) - 3600  # 1 hour ago

		# Re-sign the modified payload, re-encoding it the same way
		# generate_action_token does (base64url payload + hex signature).
		new_payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		encoded_payload = base64.urlsafe_b64encode(new_payload_json.encode("utf-8")).decode("ascii")
		new_token = f"{encoded_payload}.{_sign(new_payload_json)}"

		with self.assertRaisesRegex(frappe.ValidationError, "expired"):
			verify_action_token(new_token)
