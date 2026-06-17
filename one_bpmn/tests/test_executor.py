# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Unit tests for executor backends using mocked HTTP / SDK responses."""
import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
    ErrorCode,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    get_executor,
    register_executor,
)
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.executor.antigravity import AntigravityExecutor


def _make_config(**kwargs) -> ExecutorConfig:
    defaults = dict(
        backend="direct_api",
        provider_name="test-openai",
        model="gpt-4o",
        system_prompt="You are helpful.",
        user_prompt="Hello",
        max_retries=2,
        retry_backoff_ms=0,
        timeout_seconds=5,
    )
    defaults.update(kwargs)
    return ExecutorConfig(**defaults)


def _make_context() -> ExecutorContext:
    return ExecutorContext(
        context_doctype="Salary Slip",
        context_docname="SS-0001",
        instance_name="BPMN-0001",
        initiated_by="test@example.com",
    )


def _openai_response(content: str, prompt_tokens=10, completion_tokens=5) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _mock_provider(enabled=True, endpoint="https://api.openai.com/v1"):
    p = MagicMock()
    p.enabled = enabled
    p.api_endpoint = endpoint
    p.default_model = "gpt-4o"
    return p


class TestDirectApiExecutor(FrappeTestCase):

    def _run(self, mock_response, config=None, **response_kw):
        cfg = config or _make_config()
        ctx = _make_context()
        provider = _mock_provider()

        resp = MagicMock()
        resp.status_code = response_kw.get("status_code", 200)
        resp.json.return_value = mock_response
        resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \
             patch("requests.post", return_value=resp):
            return DirectApiExecutor().run(cfg, ctx)

    def test_text_success(self):
        result = self._run(_openai_response("Hello back!"))
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "Hello back!")
        self.assertEqual(result.token_usage.total_tokens, 15)

    def test_json_success_with_schema(self):
        schema = json.dumps({"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
        content = json.dumps({"name": "Alice"})
        cfg = _make_config(response_format="json", response_schema=schema)
        result = self._run(_openai_response(content), config=cfg)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertIsInstance(result.output, dict)
        self.assertEqual(result.output["name"], "Alice")

    def test_json_schema_validation_failed(self):
        schema = json.dumps({"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]})
        content = json.dumps({"name": "missing age"})
        cfg = _make_config(response_format="json", response_schema=schema)
        ctx = _make_context()
        provider = _mock_provider()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _openai_response(content)
        resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \
             patch("requests.post", return_value=resp):
            try:
                import jsonschema  # noqa
                result = DirectApiExecutor().run(cfg, ctx)
                self.assertEqual(result.error_code, ErrorCode.SCHEMA_VALIDATION_FAILED)
            except ImportError:
                self.skipTest("jsonschema not installed")

    def test_http_429_exhausts_retries(self):
        cfg = _make_config(max_retries=2, retry_backoff_ms=0)
        ctx = _make_context()
        provider = _mock_provider()

        resp = MagicMock()
        resp.status_code = 429
        resp.json.return_value = {}
        resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \
             patch("requests.post", return_value=resp), \
             patch("time.sleep"):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)

    def test_retry_recovery(self):
        cfg = _make_config(max_retries=2, retry_backoff_ms=0)
        ctx = _make_context()
        provider = _mock_provider()

        fail_resp = MagicMock()
        fail_resp.status_code = 429

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = _openai_response("recovered!")
        ok_resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \
             patch("requests.post", side_effect=[fail_resp, ok_resp]), \
             patch("time.sleep"):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "recovered!")

    def test_timeout(self):
        import requests as req
        cfg = _make_config()
        ctx = _make_context()
        provider = _mock_provider()

        with patch("frappe.get_doc", return_value=provider), \
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \
             patch("requests.post", side_effect=req.Timeout):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.TIMEOUT)

    def test_provider_not_found(self):
        cfg = _make_config(provider_name="nonexistent-provider")
        ctx = _make_context()
        with patch("frappe.get_doc", side_effect=frappe.DoesNotExistError):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.PROVIDER_NOT_FOUND)

    def test_provider_disabled(self):
        cfg = _make_config()
        ctx = _make_context()
        provider = _mock_provider(enabled=False)
        with patch("frappe.get_doc", return_value=provider):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.PROVIDER_DISABLED)


class TestAntigravityExecutor(FrappeTestCase):

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("antigravity") is not None,
        "google-antigravity SDK not installed"
    )
    def test_antigravity_success(self):
        cfg = _make_config(backend="antigravity")
        ctx = _make_context()

        fake_usage = MagicMock()
        fake_usage.prompt_tokens = 10
        fake_usage.completion_tokens = 5
        fake_usage.total_tokens = 15

        fake_response = MagicMock()
        fake_response.text = "AI answer"
        fake_response.usage = fake_usage

        fake_agent = MagicMock()
        fake_agent.send.return_value = fake_response

        import antigravity
        with patch.object(antigravity, "Agent", return_value=fake_agent):
            result = AntigravityExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "AI answer")
        self.assertEqual(result.token_usage.total_tokens, 15)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("antigravity") is not None,
        "google-antigravity SDK not installed"
    )
    def test_antigravity_sdk_exception(self):
        cfg = _make_config(backend="antigravity")
        ctx = _make_context()

        import antigravity
        fake_agent = MagicMock()
        fake_agent.send.side_effect = RuntimeError("SDK error")
        with patch.object(antigravity, "Agent", return_value=fake_agent):
            result = AntigravityExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
        self.assertIn("SDK error", result.error_message)

    def test_antigravity_sdk_not_installed(self):
        cfg = _make_config(backend="antigravity")
        ctx = _make_context()
        with patch.dict("sys.modules", {"antigravity": None}):
            result = AntigravityExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
        self.assertIn("google-antigravity", result.error_message)


class TestExecutorRegistry(FrappeTestCase):

    def test_get_executor_direct_api(self):
        cls = get_executor("direct_api")
        self.assertIs(cls, DirectApiExecutor)

    def test_get_executor_unknown_raises(self):
        with self.assertRaises(ValueError) as cm:
            get_executor("nonexistent_backend")
        self.assertIn("nonexistent_backend", str(cm.exception))

    def test_dummy_backend_registration(self):
        class DummyExecutor:
            pass
        register_executor("test_backend_dummy", DummyExecutor)
        cls = get_executor("test_backend_dummy")
        self.assertIs(cls, DummyExecutor)
