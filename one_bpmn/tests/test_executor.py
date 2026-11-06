# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Unit tests for executor backends using mocked HTTP / SDK responses."""
import json
import sys
import types
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
    ErrorCode,
    ExecutorConfig,
    ExecutorContext,
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
             patch("requests.post", return_value=resp), \
             patch("time.sleep"):
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
             patch("requests.post", side_effect=req.Timeout), \
             patch("time.sleep"):
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


class _FakeAgent:
    """Stands in for google.antigravity.Agent: records its config and replays canned replies."""

    def __init__(self, replies, error=None):
        self.replies = list(replies)
        self.error = error
        self.configs = []

    def __call__(self, config):
        self.configs.append(config)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def chat(self, prompt):
        if self.error:
            raise self.error
        text = self.replies.pop(0)
        usage = types.SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, thoughts_token_count=2,
            total_token_count=17, cached_content_token_count=4,
        )

        async def _text():
            return text

        return types.SimpleNamespace(text=_text, usage_metadata=usage)


def _fake_sdk(agent):
    """sys.modules entries for google.antigravity and its policy module, backed by *agent*."""
    sdk = types.ModuleType("google.antigravity")
    sdk.Agent = agent
    sdk.LocalAgentConfig = lambda **kw: types.SimpleNamespace(**kw)
    sdk.CapabilitiesConfig = lambda **kw: types.SimpleNamespace(**kw)
    hooks = types.ModuleType("google.antigravity.hooks")
    policy = types.ModuleType("google.antigravity.hooks.policy")
    policy.deny_all = lambda: "deny_all"
    hooks.policy = policy
    sdk.hooks = hooks
    return {
        "google.antigravity": sdk,
        "google.antigravity.hooks": hooks,
        "google.antigravity.hooks.policy": policy,
    }


def _gemini_model():
    if not frappe.db.exists("AI Provider", "Google"):
        frappe.get_doc({"doctype": "AI Provider", "provider": "Google"}).insert(ignore_permissions=True)  # test fixture
    if not frappe.db.exists("AI Model", "test-gemini-antigravity"):
        frappe.get_doc({
            "doctype": "AI Model",
            "model_name": "test-gemini-antigravity",
            "provider": "Google",
            "enable_model": 1,
            "api_key": "test-key-not-real",
        }).insert(ignore_permissions=True)  # test fixture
    return "test-gemini-antigravity"


class TestAntigravityExecutor(FrappeTestCase):

    def _run(self, agent, **kwargs):
        cfg = _make_config(backend="antigravity", provider_name="Google", model=_gemini_model(), **kwargs)
        with patch.dict(sys.modules, _fake_sdk(agent)):
            return get_executor("antigravity")().run(cfg, _make_context())

    def test_antigravity_success(self):
        agent = _FakeAgent(["AI answer"])
        result = self._run(agent)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "AI answer")
        self.assertEqual(result.token_usage.prompt_tokens, 10)
        self.assertEqual(result.token_usage.completion_tokens, 7)
        self.assertEqual(result.token_usage.total_tokens, 17)

    def test_antigravity_session_has_no_tools(self):
        agent = _FakeAgent(["AI answer"])
        self._run(agent)
        config = agent.configs[0]
        self.assertEqual(config.model, "test-gemini-antigravity")
        self.assertEqual(config.api_key, "test-key-not-real")
        self.assertEqual(config.capabilities.enabled_tools, [])
        self.assertFalse(config.capabilities.enable_subagents)
        self.assertEqual(config.policies, ["deny_all"])
        self.assertEqual(config.workspaces, [config.app_data_dir])

    def test_antigravity_sdk_exception(self):
        with patch("time.sleep"):
            result = self._run(_FakeAgent([], error=RuntimeError("SDK error")))
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
        self.assertIn("SDK error", result.error_message)
        self.assertEqual(len(result.attempts), 3)

    def test_antigravity_json_success_with_schema(self):
        schema = json.dumps(
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        )
        result = self._run(_FakeAgent([json.dumps({"name": "Alice"})]), response_format="json", response_schema=schema)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, {"name": "Alice"})

    def test_antigravity_json_schema_validation_failed(self):
        schema = json.dumps(
            {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
        )
        reply = json.dumps({"name": "missing age"})
        result = self._run(_FakeAgent([reply, reply]), response_format="json", response_schema=schema)
        self.assertEqual(result.error_code, ErrorCode.SCHEMA_VALIDATION_FAILED)

    def test_antigravity_needs_a_google_provider(self):
        cfg = _make_config(backend="antigravity")
        with patch.dict(sys.modules, _fake_sdk(_FakeAgent(["unused"]))):
            result = AntigravityExecutor().run(cfg, _make_context())
        self.assertEqual(result.error_code, ErrorCode.PROVIDER_NOT_FOUND)

    def test_antigravity_sdk_not_installed(self):
        cfg = _make_config(backend="antigravity", provider_name="Google", model=_gemini_model())
        with patch.dict(sys.modules, {"google.antigravity": None}):
            result = AntigravityExecutor().run(cfg, _make_context())
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
        self.assertIn("bench setup requirements", result.error_message)


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
