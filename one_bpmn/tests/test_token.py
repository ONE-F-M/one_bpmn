"""Unit tests for :mod:`one_bpmn.utils.token`.

These are pure Python tests — no Frappe site required.  The Frappe
secret is mocked to a deterministic value.
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest


# A deterministic secret for reproducible test signatures
_TEST_SECRET = "test-secret-key-for-unit-tests"


@pytest.fixture(autouse=True)
def _mock_secret():
	"""Patch the HMAC secret so tests don't need a Frappe site."""
	with patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET):
		yield


class TestGenerateActionToken:
	"""Tests for :func:`generate_action_token`."""

	def test_generate_returns_string(self):
		"""Token is a non-empty string with a dot separator."""
		from one_bpmn.utils.token import generate_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		assert isinstance(token, str)
		assert len(token) > 0
		assert "." in token

	def test_payload_fields(self):
		"""Decoded payload contains all expected keys."""
		from one_bpmn.utils.token import generate_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		payload_json = token.rsplit(".", 1)[0]
		payload = json.loads(payload_json)

		assert payload["instance_name"] == "INST-001"
		assert payload["task_id"] == "task-uuid"
		assert payload["action"] == "Approve"
		assert payload["user"] == "user@test.com"
		assert "expires" in payload
		assert payload["expires"] > time.time()


class TestVerifyActionToken:
	"""Tests for :func:`verify_action_token`."""

	def test_roundtrip(self):
		"""generate → verify returns the original payload."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")
		payload = verify_action_token(token)

		assert payload["instance_name"] == "INST-001"
		assert payload["task_id"] == "task-uuid"
		assert payload["action"] == "Approve"
		assert payload["user"] == "user@test.com"

	def test_tampered_token_rejected(self):
		"""Modifying any character in the token raises AuthenticationError."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token
		import frappe

		token = generate_action_token("INST-001", "task-uuid", "Approve", "user@test.com")

		# Tamper with the signature (last 4 chars)
		tampered = token[:-4] + "XXXX"

		with pytest.raises(frappe.AuthenticationError):
			verify_action_token(tampered)

	def test_expired_token_rejected(self):
		"""Token with expires in the past raises ValidationError."""
		from one_bpmn.utils.token import generate_action_token, verify_action_token
		import frappe

		# Generate a token that expired 1 hour ago
		token = generate_action_token(
			"INST-001", "task-uuid", "Approve", "user@test.com",
			expiry_hours=0,
		)
		# Manually create an expired token by patching time
		payload_json = token.rsplit(".", 1)[0]
		payload = json.loads(payload_json)
		payload["expires"] = int(time.time()) - 3600  # 1 hour ago

		# Re-sign with the expired payload
		from one_bpmn.utils.token import _sign
		new_payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		new_token = f"{new_payload_json}.{_sign(new_payload_json)}"

		with pytest.raises(frappe.ValidationError, match="expired"):
			verify_action_token(new_token)
