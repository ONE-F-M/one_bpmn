"""Unit tests for :mod:`one_bpmn.processa_engine.notifications.token`.

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
		self._secret_patch = patch("one_bpmn.processa_engine.notifications.token._get_secret", return_value=_TEST_SECRET)
		self._secret_patch.start()
		self.addCleanup(self._secret_patch.stop)

	def test_generate_returns_string(self):
		"""Token is a non-empty string with a dot separator."""
		from one_bpmn.processa_engine.notifications.token import generate_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		self.assertIsInstance(token, str)
		self.assertTrue(len(token) > 0)
		self.assertIn(".", token)

	def test_payload_fields(self):
		"""Decoded payload contains all expected keys."""
		from one_bpmn.processa_engine.notifications.token import generate_action_token

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
		self._secret_patch = patch("one_bpmn.processa_engine.notifications.token._get_secret", return_value=_TEST_SECRET)
		self._secret_patch.start()
		self.addCleanup(self._secret_patch.stop)

	def test_roundtrip(self):
		"""generate → verify returns the original payload."""
		from one_bpmn.processa_engine.notifications.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		payload = verify_action_token(token)

		self.assertEqual(payload["instance_name"], "INST-001")
		self.assertEqual(payload["task_id"], "task-uuid")
		self.assertEqual(payload["action"], "Approve")
		self.assertEqual(payload["user"], "user@test.com")

	def test_tampered_token_rejected(self):
		"""Modifying any character in the token raises AuthenticationError."""
		from one_bpmn.processa_engine.notifications.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")

		# Tamper with the signature (last 4 chars)
		tampered = token[:-4] + "XXXX"

		with self.assertRaises(frappe.AuthenticationError):
			verify_action_token(tampered)

	def test_expired_token_rejected(self):
		"""Token with expires in the past raises ValidationError."""
		from one_bpmn.processa_engine.notifications.token import _sign, generate_action_token, verify_action_token

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

	def test_allow_expired_returns_flag(self):
		"""allow_expired returns the payload with expired true instead of raising."""
		from one_bpmn.processa_engine.notifications.token import _sign, generate_status_token, verify_action_token

		payload = _decode_payload(generate_status_token("INST-001", "task-uuid"))
		payload["expires"] = int(time.time()) - 3600
		payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
		token = f"{encoded}.{_sign(payload_json)}"

		result = verify_action_token(token, allow_expired=True)
		self.assertTrue(result["expired"])
		self.assertEqual(result["instance_name"], "INST-001")

	def test_allow_expired_flag_false_when_valid(self):
		from one_bpmn.processa_engine.notifications.token import generate_status_token, verify_action_token

		result = verify_action_token(generate_status_token("INST-001", "task-uuid"), allow_expired=True)
		self.assertFalse(result["expired"])

	def test_allow_expired_still_rejects_tampered(self):
		from one_bpmn.processa_engine.notifications.token import generate_status_token, verify_action_token

		token = generate_status_token("INST-001", "task-uuid")[:-4] + "XXXX"
		with self.assertRaises(frappe.AuthenticationError):
			verify_action_token(token, allow_expired=True)


class TestGenerateStatusToken(FrappeTestCase):
	"""Tests for :func:`generate_status_token`."""

	def setUp(self):
		self._secret_patch = patch("one_bpmn.processa_engine.notifications.token._get_secret", return_value=_TEST_SECRET)
		self._secret_patch.start()
		self.addCleanup(self._secret_patch.stop)

	def test_expiry_hours(self):
		"""expiry_hours=24 expires 24 hours after creation."""
		from one_bpmn.processa_engine.notifications.token import generate_status_token, verify_action_token

		before = int(time.time())
		payload = verify_action_token(generate_status_token("INST-001", "task-uuid", expiry_hours=24))
		after = int(time.time())

		self.assertGreaterEqual(payload["expires"], before + 24 * 3600)
		self.assertLessEqual(payload["expires"], after + 24 * 3600)

	def test_default_is_thirty_days(self):
		"""Without expiry_hours the lifetime stays at 30 days."""
		from one_bpmn.processa_engine.notifications.token import generate_status_token

		before = int(time.time())
		payload = _decode_payload(generate_status_token("INST-001", "task-uuid"))
		after = int(time.time())

		self.assertGreaterEqual(payload["expires"], before + 30 * 86400)
		self.assertLessEqual(payload["expires"], after + 30 * 86400)
		self.assertNotIn("user", payload)

	def test_user_and_empty_task_id(self):
		from one_bpmn.processa_engine.notifications.token import generate_status_token

		payload = _decode_payload(generate_status_token("INST-001", user="user@test.com"))
		self.assertEqual(payload["user"], "user@test.com")
		self.assertEqual(payload["task_id"], "")
		self.assertEqual(payload["type"], "status")


# Made by the token module before the generators shared _seal, with _TEST_SECRET and expires 4102444800.
OLD_TOKENS = {
	"action": "eyJhY3Rpb24iOiJBcHByb3ZlIiwiZXhwaXJlcyI6NDEwMjQ0NDgwMCwiaW5zdGFuY2VfbmFtZSI6IklOU1QtMDAxIiwidGFza19pZCI6InRhc2stdXVpZCIsInVzZXIiOiJ1c2VyQHRlc3QuY29tIn0=.5eb6dc9f1edf0d5b91625ed74eec36bd8280cad6ce7076c2be8ed512428b5eb2",
	"doc_action": "eyJhY3Rpb24iOiJDb21tZW50IiwiZG9jbmFtZSI6IkhSLUxBUC0wMDAxIiwiZG9jdHlwZSI6IkxlYXZlIEFwcGxpY2F0aW9uIiwiZXhwaXJlcyI6NDEwMjQ0NDgwMCwidXNlciI6InVzZXJAdGVzdC5jb20ifQ==.4d45093484d2321cdbd49d881dbfaeedae89963117c338eb81508385b95192ef",
	"status": "eyJleHBpcmVzIjo0MTAyNDQ0ODAwLCJpbnN0YW5jZV9uYW1lIjoiSU5TVC0wMDEiLCJ0YXNrX2lkIjoidGFzay11dWlkIiwidHlwZSI6InN0YXR1cyIsInVzZXIiOiJ1c2VyQHRlc3QuY29tIn0=.db8b0a1bb00b965b9e1df0dc21fc89ad7fb92522d635727a67c50a761a4f4e3a",
}
OLD_TOKENS_ISSUED_AT = 4102444800 - 72 * 3600


class TestSealKeepsOldTokens(FrappeTestCase):
	"""Tokens sealed before the generators shared _seal still validate, and the generators make the same strings."""

	def setUp(self):
		patcher = patch("one_bpmn.processa_engine.notifications.token._get_secret", return_value=_TEST_SECRET)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_old_tokens_validate(self):
		from one_bpmn.processa_engine.notifications.token import verify_action_token

		self.assertEqual(verify_action_token(OLD_TOKENS["action"])["action"], "Approve")
		self.assertEqual(verify_action_token(OLD_TOKENS["doc_action"])["docname"], "HR-LAP-0001")
		self.assertEqual(verify_action_token(OLD_TOKENS["status"])["type"], "status")

	def test_generators_match_old_tokens(self):
		from one_bpmn.processa_engine.notifications import token

		with patch.object(token.time, "time", return_value=OLD_TOKENS_ISSUED_AT):
			self.assertEqual(
				token.generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com"), OLD_TOKENS["action"]
			)
			self.assertEqual(
				token.generate_doc_action_token("Leave Application", "HR-LAP-0001", "Comment", "user@test.com"),
				OLD_TOKENS["doc_action"],
			)
			self.assertEqual(
				token.generate_status_token("INST-001", "task-uuid", expiry_hours=72, user="user@test.com"),
				OLD_TOKENS["status"],
			)

	def test_every_generator_seals_through_seal(self):
		from one_bpmn.processa_engine.notifications import token

		with patch.object(token, "_seal", return_value="sealed") as seal:
			results = [
				token.generate_action_token("I", "T", "Approve", "u@test.com"),
				token.generate_conversation_token("I", "T", "u@test.com", "thread"),
				token.generate_doc_action_token("Note", "N-1", "Comment", "u@test.com"),
				token.generate_status_token("I", "T"),
				token.generate_file_token("F-1", "Note", "N-1"),
			]
		self.assertEqual(results, ["sealed"] * 5)
		self.assertEqual(seal.call_count, 5)
